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
/**
 * 잡 · 패널이 쓴 자격의 갈래 — 잡을 만든 사람(requester) · 대상 소유자(owner). 패널은 서비스 계정으로 내려가지 않는다
 * (runner.resolve_credential_with_note · U-3). `service` 는 그 전에 돈 패널의 quality 에만 남아 있을 수 있다.
 */
export type Credential = "requester" | "owner" | "service";

/** 반영 상태(ra_client — pending · done · unavailable). 화면은 모르는 값도 글자 그대로 보인다. */
export type SyncState = "pending" | "done" | "unavailable";

/**
 * 반영 요약 한 채널(ra_client.sync_summary) — 과제 상세의 `targets[]` · `GET /targets` · 진행판이 싣는다. `pending_ops` 는 건수다.
 * 전에 채널 값을 글자(SyncState)로 적어 두어 배지가 이 객체를 React 자식으로 그리다 과제 화면이 백지가 됐다(React #31).
 */
export type SyncSummary = { state: SyncState | (string & {}); pending_ops: number; reason: string | null; message: string };
export type ExternalSync = { ra: SyncSummary; adh: SyncSummary };

/** 재동기 응답의 한 채널(ra_client.resync — external_sync_json 그대로). `pending_ops` 는 op 목록이다(요약과 다르다). */
export type SyncEntry = {
  state: SyncState | (string & {});
  attempts: number;
  next_at: number;
  last_error: string | null;
  done_at: number | null;
  pending_ops: JsonValue[];
};

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

/** 등록이 어디서 왔나(routes.PAT_SOURCES · GATEWAY_PAT_SOURCE). `PUT /me/portal-pat` 가 받는 것은 web · manual 뿐이다. */
export type PortalPatSource = "web" | "gateway-exchange" | "manual";
/** 지금 발급해 등록해야 하는 까닭(routes.pat_due_reason) — 앞의 것이 먼저다. audience 는 step-forge 청중이 없다는 뜻이다. */
export type PortalPatDueReason = "absent" | "revoked" | "undecryptable" | "expiring" | "audience";

/**
 * `GET /me` 의 `portal_pat.auto`(routes.portal_pat_auto) — 자동 등록 스위치와 마지막 자동 등록 · 실패.
 * `PUT /me/portal-pat-auto` 의 답도 이 꼴 하나다.
 */
export type PortalPatAuto = {
  /** 사용자가 끄지 않았다. */
  enabled: boolean;
  /** 지금 발급해 등록해야 한다 — 화면은 `enabled && due` 면 조용히 한 번 한다. */
  due: boolean;
  due_reason: PortalPatDueReason | null;
  last_source: PortalPatSource | null;
  last_at: number | null;
  /** `"<code>: <앱이 고른 글>"` — 할 일을 말한다. 글자 그대로 보인다. */
  last_error: string | null;
  /** transient 는 앱이 10분 뒤 다시 바란다 · final 은 사람이 고쳐야 한다. */
  last_error_kind: "transient" | "final" | null;
  last_error_at: number | null;
  /** 켜져 있을 때만 — 지우거나 폐기해도 다시 만들어지니 멈추려면 끈다는 글. */
  how_to_stop: string | null;
};

/**
 * `GET /me` 의 `portal_pat` — 로그인한 사람에게는 늘 객체다(등록이 없으면 `registered:false` 와 `auto` 만 있다).
 * 익명과 박스 불일치(이관 직후)는 `Me.portal_pat` 이 null 이다. PAT 원문·암호문은 응답에 없다.
 */
export type PortalPatSummary = {
  registered: boolean;
  email: string | null;
  groups: string[];
  exp: number | null;
  /** 등록 시 강제된 PAT 스코프(계획 §8.2.7 — 읽기 전용 `['read']`). 등록이 있을 때만 온다. */
  scopes?: string[];
  /** 포털이 폐기한 PAT 는 시각이 찍힌다 — 화면은 '이 PAT 는 폐기됨 — 재등록하세요' 를 띄운다. */
  revoked_at?: number | null;
  /** 폐기 대조 키(§8.2.7). 포털 토큰 페이지의 항목과 대조한다. */
  jti?: string | null;
  /** false 면 저장된 암호문을 현재 키로 풀 수 없다 — 화면엔 '등록됨' 인데 러너는 그 자격을 쓰지 못한다. */
  decryptable?: boolean;
  auto: PortalPatAuto;
};

/**
 * `PUT /me/portal-pat` 의 답(routes._register_portal_pat · 삭제) — `GET /me` 의 요약과 꼴이 다르다(`auto`·`revoked_at`·
 * `decryptable` 이 없다). 그래서 화면은 등록 뒤 `GET /me` 를 다시 읽는다.
 */
export type PortalPatPutResult =
  | { registered: true; email: string; groups: string[]; exp: number; scopes: string[]; jti: string }
  | { registered: false; email: null; groups: string[]; exp: null };

/** `GET /me` 의 `box.reasons[]`(config.box_assessment). 익명에게는 code 만 온다. */
export type BoxReason = {
  code:
    | "host_mismatch"
    | "missing_required"
    | "cred_key_invalid"
    | "cred_key_dev_fallback"
    | "cred_key_path_missing"
    | "missing_optional";
  keys?: string[];
  message?: string;
  fix?: string;
};

export type Me = {
  email: string | null;
  display_name: string | null;
  role: string | null;
  organization: string | null;
  anonymous: boolean;
  source: "bearer" | "cookie" | "sso" | "none";
  portal_pat: PortalPatSummary | null;
  /** cred_key_present=false 면 PAT 등록이 422 `cred_key_absent` 로 거부된다(§8.2.7). */
  box: {
    hostname: string;
    secrets_valid: boolean;
    cred_key_present: boolean;
    /** 앱이 포털을 부르는 주소. 틀리면 PAT 등록·패널 실행이 전부 실패한다(비밀이 아니다). */
    portal_base: string;
    reasons: BoxReason[];
    /** 로그인한 사람에게만 온다. */
    cred_key_source?: "secrets" | "env" | "path" | "dev_fallback" | "absent";
  };
};

/** `GET /meta/adapters` 의 소스 카드 선택지(§8.2.3 각주) — 지금 서버는 늘 빈 배열이다(소스 앱 도구를 불러야 채워진다). */
export type AdapterChoice = { value: string; label: string; detail?: string | null };
/**
 * `GET /meta/adapters` 의 kind 한 줄(adapters/registry.discover_adapters — 게이트웨이 `/tools-map` 실측, 60초 캐시).
 * `status` 는 ready(도구가 다 보인다) · unavailable(빠진 원래 이름이 `tools_missing`) · planned(게이트웨이 도구 지도를 못 읽었다)다.
 * '도구가 없다' 와 '못 물어봤다' 는 다르다 — 앞은 운영자 몫, 뒤는 잠시 뒤 다시.
 */
export type AdapterEntry = {
  kind: string;
  app_key: string | null;
  status: AdapterStatus | (string & {});
  tools_ok: boolean;
  tools_missing: string[];
  gateway_error: string | null;
  /** 발견 경고(`ambiguous_tool_name` 따위). */
  warnings: string[];
  choices: AdapterChoice[];
};
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

/** 과제 등급 — 반출 경계다(plan §5.2.5 (3a)). 등록할 때 사람이 고른다 — 빠지면 422 `classification_required`. */
export type Classification = "internal" | "confidential";
export const CLASSIFICATIONS: readonly Classification[] = ["internal", "confidential"];

/** 과제 수명 주기(routes.LIFECYCLES) — active 를 떠나면 서버가 closed_at 을 찍는다. */
export type Lifecycle = "active" | "shipped" | "cancelled" | "archived";
export const LIFECYCLES: readonly Lifecycle[] = ["active", "shipped", "cancelled", "archived"];
/** MCP 공개 범위(routes.MCP_VISIBILITIES) — private 는 소유자 · 구성원만, org 는 조직의 다른 심의 도구도 본다. 소유자만 바꾼다. */
export type McpVisibility = "private" | "org";
/** 코퍼스 제외 사유(routes.EXCLUDED_REASONS). */
export type ExcludedReason = "fixture" | "misregistered" | "duplicate" | "user";
export const EXCLUDED_REASONS: readonly ExcludedReason[] = ["fixture", "misregistered", "duplicate", "user"];
/** 과제에서의 역할(routes.ROLE_RANK) — 소유자는 늘 owner 이고 멤버 행은 viewer · editor 다. */
export type ProjectRole = "owner" | "editor" | "viewer";

/**
 * 제품 연결 한 행(plan §8.2.4 RiskHomePage — `product_refs_json`). `kind` 는 ra_model(RA 모델 엔티티) · product_code(VOC · 필드 조회
 * 키)다. 서버는 `kind='product_code'` 인 첫 행을 대표값 `product_code` 로 쓴다(routes.create_project).
 */
export type ProductRef = { kind: "ra_model" | "product_code"; value: string };

export type ProjectCreate = {
  code: string;
  name: string;
  classification: Classification;
  stage?: string | null;
  predecessor_project_id?: string | null;
  /** 제품 연결 — 비면 보내지 않는다(빈 배열과 '안 보냄' 이 서버에서 같은 값이 되게). */
  product_refs_json?: ProductRef[];
  adh_scope: AdhScope;
};

/**
 * 과제 행(routes._project_row) — `POST /projects` 의 답이자 `GET /projects/{id}` 의 `project`.
 * 서버 열 이름 그대로다 — `adh_scope` 는 보낼 때만의 꼴이고 받을 때는 `adh_team`·`adh_group` 두 열이다.
 *
 * 물음표 칸은 계약(plan §8.2.3 · §8.2.4 ProjectPage 머리)에 있지만 9bd5f48 의 `_project_row` 가 싣지 않는 열이다 — 화면은 오면 쓰고,
 * 없으면 '이 서버가 주지 않는다' 로 보인다(값을 지어내지 않는다). `PATCH` 의 답(`ProjectMeta`)은 이 열들을 싣는다.
 */
export type Project = {
  id: string;
  owner_sub: string;
  code: string;
  name: string;
  stage: string | null;
  predecessor_project_id: string | null;
  adh_team: string | null;
  adh_group: string | null;
  character_status: string | null;
  created_at: number;
  updated_at: number;
  classification?: Classification | null;
  lifecycle?: Lifecycle | null;
  closed_at?: number | null;
  corpus_excluded?: boolean | number | null;
  excluded_reason?: ExcludedReason | null;
  mcp_visibility?: McpVisibility | null;
  product_code?: string | null;
  /** 서버 열은 JSON 글자다(canonical_json) — 받을 때 배열로 올 수도 글자로 올 수도 있어 화면이 푼다. */
  product_refs_json?: ProductRef[] | string | null;
  predecessor_product_code?: string | null;
  status?: string | null;
};

/**
 * `PATCH /projects/{id}` 의 `project`(routes.patch_project — rr_projects 열 그대로). `corpus_excluded` 는 0 · 1,
 * `product_refs_json` 은 JSON 글자다.
 */
export type ProjectMeta = {
  id: string;
  owner_sub: string;
  code: string;
  name: string;
  stage: string | null;
  lifecycle: Lifecycle | (string & {}) | null;
  closed_at: number | null;
  corpus_excluded: number;
  excluded_reason: ExcludedReason | (string & {}) | null;
  classification: Classification | (string & {}) | null;
  mcp_visibility: McpVisibility | (string & {}) | null;
  product_code: string | null;
  product_refs_json: string | null;
  predecessor_product_code: string | null;
  status: string | null;
  created_at: number;
  updated_at: number;
};

export type ProjectPatch = {
  lifecycle?: Lifecycle;
  corpus_excluded?: boolean;
  excluded_reason?: ExcludedReason;
  classification?: Classification;
  mcp_visibility?: McpVisibility;
  product_code?: string | null;
  product_refs_json?: ProductRef[] | null;
  predecessor_product_code?: string | null;
};

export type ProjectPatched = {
  project: ProjectMeta;
  recomputed: { delta_priors_rows: number; patterns_rows: number };
  /** mcp_visibility 를 바꿨을 때만 — RA 보류(withheld)에서 풀린 대상 수 · op 수와 AIDataHub 태그 재부착 op 수. */
  resynced?: { targets: number; ra_ops_released: number; adh_retag_ops?: number };
};

/** 멤버 한 줄(routes._members_of). 소유자 행(role owner)도 함께 온다. */
export type ProjectMember = {
  project_id: string;
  email: string;
  role: ProjectRole | (string & {});
  added_by: string | null;
  added_at: number | null;
  updated_at: number | null;
};
export type ProjectMembers = { project_id: string; members: ProjectMember[] };
/** `PUT /projects/{id}/members` 본문(routes.MembersBody) — 넣거나 바꿀 멤버(viewer · editor)와 뺄 이메일. 소유자 행은 못 바꾼다. */
export type ProjectMembersPut = { members: Array<{ email: string; role: "viewer" | "editor" }>; remove: string[] };

/** `POST /projects/{id}/transfer` 의 답 — 하위 표마다 옮긴 행 수. */
export type ProjectTransferred = { from: string; to: string; rows_updated: { tables: Record<string, number> } };

/** `POST /projects/{id}/purge` 의 답(routes.purge_project — 동기로 끝난다). */
export type ProjectPurged = {
  job_id: string;
  status: "purged";
  purge_report: {
    project_id: string;
    purged_at: number;
    by: string;
    reason: string;
    layers: JsonObject;
    remaining: Array<{ layer: string; reason: string; detail: string }>;
  };
};

/** `GET /projects/{id}/audit` 한 줄(routes.get_project_audit — rr_audit 행, before · after 는 풀린 객체). */
export type AuditEntry = {
  id: string;
  actor: string;
  actor_verified: boolean;
  channel: string | null;
  scope: string;
  subject_id: string | null;
  project_id: string | null;
  action: string;
  before: JsonValue;
  after: JsonValue;
  reason: string | null;
  at: number;
};
export type AuditPage = { project_id: string; total: number; limit: number; offset: number; entries: AuditEntry[] };

/**
 * 과제 상세의 소스 카드 한 장(routes._project_sources). `probe` 는 연결 · 캡처가 잰 값이고 비어 있을 수 있다({}) — 그때 `status` 는
 * unlinked 다. ECAD 카드는 과제마다 많아야 한 장이고 `ref` 가 `{odb_job_id}`, `probe.board` 가 붙은 보드의 정체다.
 */
export type ProjectSource = {
  id: string;
  kind: SourceKind;
  app_key: string | null;
  /** 서버가 파싱해 보내는 객체다 — 문자열이 아니다(`SourceRef` 주석 참조). 없으면 빈 객체다. */
  ref: SourceRef;
  bridge_declared: boolean;
  probe: SourceProbe;
  probe_at: number | null;
  status: SourceStatus | (string & {});
};

/** `GET /projects` 카드의 소스 줄 — 상태만 싣는다. */
export type ProjectSourceBrief = { kind: string; app_key: string | null; status: SourceStatus | (string & {}) };

/**
 * `GET /projects` 의 카드 1장(routes.projects_payload). 물음표 칸(등급 · 수명 주기 · 코퍼스 제외 · 내 역할)은 계약(plan §8.2.3)에
 * 있지만 9bd5f48 서버가 싣지 않는다 — 화면은 오면 칩을 그리고, 없으면 거름을 잠근다.
 */
export type ProjectCard = {
  id: string;
  code: string;
  name: string;
  stage: string | null;
  targets: string[];
  last_snapshot_id: string | null;
  sources: ProjectSourceBrief[];
  last_snapshot_at: number | null;
  open_targets: number;
  /** 대상이 없거나 로스터가 비면 null 이다(0 이 아니다). */
  coverage_pct: number | null;
  /** 대상이 없으면 null 이다. */
  level: CoverageLevel | null;
  classification?: Classification | null;
  lifecycle?: Lifecycle | null;
  corpus_excluded?: boolean | number | null;
  my_role?: ProjectRole | null;
};

export type ProjectList = { projects: ProjectCard[] };

/**
 * 과제 상세의 스냅샷 한 줄(`GET /projects/{id}` → `snapshots[]`).
 *
 * **서버 열 이름 그대로 둔다.** 여기에 서버에 없는 이름(`label`·`captured_at`·`kinds`)을 적어
 * 두었더니 `tsc` 가 통과하고 화면은 런타임에 깨졌다 — `s.kinds.join()` 이 undefined 를 불렀다.
 * 타입이 거짓이면 타입검사는 거짓을 지켜 준다.
 */
export type SnapshotHeader = {
  id: string;
  ir_version: string;
  ir_hash: string;
  /** 서버는 JSON **문자열**로 준다(`kinds_json` 을 변환 없이 내보낸다). 쓰는 쪽에서 파싱한다. */
  kinds_json: string;
  node_count: number;
  edge_count: number;
  warnings_n: number;
  degraded: boolean;
  created_at: number;
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

/**
 * 과제 상세의 잡 한 줄(`GET /projects/{id}` → `jobs[]`) — 대상에 묶인 패널 · 검토 잡이다(routes.get_project).
 * `progress` 는 숫자가 아니라 객체다 — 패널 수(done · total)에 잡의 진행 기록(progress_json)이 펼쳐져 온다. 전에 숫자로 적어 두어
 * 진행 칸이 'NaN%' 였다.
 */
export type JobHeader = {
  id: string;
  target_key: string;
  tier: string | null;
  kind: "panel_batch" | "review_batch";
  mode: string;
  state: SnapshotJobState | BatchJobState;
  progress: { done: number | null; total: number | null; [key: string]: JsonValue | undefined };
  error: string | null;
};

export type ProjectDetail = {
  project: Project;
  /** 계약(plan §8.2.3)에는 있지만 9bd5f48 서버는 싣지 않는다 — 멤버 탭은 `GET /projects/{id}/members` 를 따로 부른다. */
  members?: Array<{ email: string; role: string }>;
  sources: ProjectSource[];
  snapshots: SnapshotHeader[];
  targets: TargetHeader[];
  jobs: JobHeader[];
  /** 성격 태그와 그 수(많은 순 10개) — 글자 목록이 아니라 `{tag, n}` 이다. 전에 글자로 적어 두어 태그가 있는 과제가 백지였다. */
  character_top_tags: Array<{ tag: string; n: number }>;
};

/**
 * 일반 소스 연결(routes.SourceBody) — `ref` 는 **객체**다(서버 칸이 dict 다). 전에 글자로 보내 늘 422 였다. ECAD 는 이 길로 붙이지
 * 않는다(422 `ecad_board_route` — 보드 찾기 · 붙이기 길을 쓴다).
 */
export type SourceCreate = {
  kind: Exclude<SourceKind, "ecad">;
  app_key: string;
  ref: Record<string, string>;
  bridge_declared?: boolean;
};

/**
 * 연결된 소스의 `ref` — 서버는 `_loads(row["ref_json"], {})` 로 **파싱한 객체**를 준다
 * (routes.py `_project_sources`). 전에 `ref: string` 이라 적어 두어 화면이 이 객체를 React
 * 자식으로 그리다 통째로 백지가 됐다(React error #31). 모양은 kind 마다 다르다 —
 * mcad 는 `{stepforge_project_id, detect_job_id}`, dyna 는 `{session_id, file_id, sha256}`, ecad 는 `{odb_job_id}`.
 */
export type SourceRef = Record<string, string | number | boolean | null>;

/**
 * 소스 카드의 도달 측정(probe_json). 연결 때 한 번 적고 캡처가 다시 잰다. 카드가 막 생겼거나 잰 적이 없으면 빈 객체라 칸마다 없을
 * 수 있다. ECAD 카드는 `board`(붙인 보드의 정체 — 캡처 뒤에도 남는다)를 싣는다.
 */
export type SourceProbe = {
  reachable?: boolean;
  detail?: string;
  capture_mode?: string | null;
  status?: SourceStatus | (string & {});
  board?: EcadBoard;
};
/** `POST /projects/{id}/sources` 의 답 — mcad 면 `warnings ∋ stepforge_no_isolation`(StepForge 에는 사용자 격리가 없다). */
export type SourceCreated = { ok: boolean; probe: SourceProbe; warnings?: string[] };

// ── ECAD 보드(포털 docs/design-risk-review/ecad-1031 frontend-request — main 9bd5f48) ──────────────

/** find_job 후보 한 줄(adapters/ecad.candidate_of) — 허브 칸 그대로이고 `name` 만 과제 · 모델 · 보드 종류 · 판을 ` / ` 로 엮었다. */
export type EcadBoard = {
  job_id: string | null;
  /** 넷 다 비면 null 이다(지어내지 않는다). */
  name: string | null;
  project: string | null;
  model: string | null;
  board_type: string | null;
  revision: string | null;
  original_filename: string | null;
  uploaded_at: string | null;
};

/** `GET /ecad/boards?q=` 의 답 — 많아야 10개이고 `truncated` 면 더 있다. 허브가 '없다' 를 봉투 오류로 답하면 `hub_message`. */
export type EcadBoardSearch = {
  query: string;
  app_key: string;
  tool: string;
  candidates: EcadBoard[];
  truncated: boolean;
  hub_message?: string;
};

/** `PUT /projects/{id}/ecad-board {odb_job_id}` 의 답 — `source` 는 새로 적힌 ECAD 카드다. */
export type EcadBoardPut = {
  ok: true;
  project_id: string;
  ecad_board: EcadBoard;
  source: ProjectSource;
  previous_odb_job_id: string | null;
  changed: boolean;
};

/** `DELETE /projects/{id}/ecad-board` 의 답 — 붙은 것이 없었으면 `removed: 0` 이다. */
export type EcadBoardDeleted = { ok: true; project_id: string; removed: number; previous_odb_job_id: string | null };

// ── 스냅샷 ────────────────────────────────────────────────────────────────────

/**
 * 스냅샷 동결 본문(routes.SnapshotBody). `kinds` 가 비면 붙은 카드 전부를 읽는다. `report_ids` 는 수다(서버 칸이 list[int]).
 * `allow_large` 는 409 `model_too_large` 를 본 사람이 '그래도 동결' 을 고른 뒤에만 싣는다.
 */
export type SnapshotCreate = {
  label?: string;
  kinds: SourceKind[];
  report_ids?: number[];
  detect_result_file_id?: string;
  allow_large?: true;
};

/**
 * 스냅샷 동결의 답(routes.create_snapshot — **동기**다, 202 잡이 아니다). 같은 ir_hash 가 이미 있으면 `reused` 다.
 * `gates_summary` 는 게이트마다 true · false · null(검문할 입력이 없었다 — 위반이 아니다)이다.
 */
export type SnapshotCreated = {
  snapshot_id: string;
  ir_hash: string;
  reused: boolean;
  partial: boolean;
  blocked: boolean;
  gates_summary: Partial<Record<GateId, boolean | null>>;
  degraded: string[];
  job_id: string;
  job_state: "done" | "partial" | (string & {});
  calls_reused: number;
  /** 이번 캡처가 읽은 자격 — mcp 는 user(본인 포털 PAT) · service(박스 읽기 PAT) · null. */
  credentials: { mcp: string | null; rest: string | null; rest_ok: boolean; rest_bridge?: JsonObject };
  context?: JsonObject;
  context_frozen_at?: number | null;
  context_changed?: boolean | null;
};

/** 409 `model_too_large` 의 detail(routes._check_model_size) — `leaf` 는 MCAD 리프와 ECAD 부품의 합이다(사용자 결정 10-31). */
export type ModelTooLarge = {
  leaf: number;
  leaf_mcad: number;
  leaf_ecad: number;
  interfaces: number;
  max_leaf: number;
  max_interfaces: number;
  budget_s: number;
};

/**
 * 409 `source_unreachable` 의 detail — 붙은 카드를 kinds 가 다 뺐으면 `{kinds, attached}`(kinds 를 고칠 일), 이번 캡처가 읽은 카드가
 * ECAD 하나뿐인데 보드를 못 읽었으면 `{kind: "ecad", reason}`(어댑터 경고 code — ecad_pat_absent · ecad_board_not_found 따위)이다.
 */
export type SourceUnreachable = { kinds?: string[]; attached?: string[]; kind?: string; reason?: string | null };

/** 단일 스냅샷 게이트 G1 ~ G6 과 비교 전용 G7. */
export type GateId = "G1" | "G2" | "G3" | "G4" | "G5" | "G6" | "G7";

/**
 * 게이트 한 칸(state.compute_gates — rr_state.gates 의 값). `pass` 는 true · false · **null** 이고 null 은 검문할 입력이 통째로 없다는
 * 뜻이다(`reason` 이 까닭 — mcad_absent · capture_partial · unit_only · warnings_unavailable · unit_unknown). null 은 fail 이 아니다 —
 * 다만 G6 의 unit_unknown 은 차단을 유지한다(unknown_blocking). ack 는 판정(pass)을 바꾸지 않는다.
 */
export type GateRecord = {
  key: string;
  count: number | null;
  threshold: number | null;
  pass: boolean | null;
  reason?: string | null;
  blocking: boolean;
  effect: string;
  ack_by?: string | null;
  ack_at?: number | null;
  ack_reason?: string | null;
  detail: JsonValue[];
};
export type Gates = Partial<Record<GateId, GateRecord>>;

/** `POST /snapshots/{id}/gates/{G}/ack` 의 답. ack 해도 pass 는 그대로다. */
export type GateAcked = {
  gate: GateId;
  ack_by: string | null;
  ack_at: number | null;
  ack_reason: string | null;
  gates_hash: string;
  pass: boolean | null;
  revoked_by?: string;
  revoked_at?: number;
};

/** rr_ir 노드(rr_ir.v1.json definitions.node). `attrs` 는 도메인 · kind 마다 칸이 다르다(board 노드는 `EcadBoardAttrs`). */
export type IrNode = {
  nid: string;
  canon_key: string;
  domain: "mcad" | "dyna" | "ecad" | (string & {});
  /** part · assembly · file · pid · contact_set · component · net · layer · board. */
  kind: string;
  label: string;
  local_key: string;
  name_norm: string;
  name_norm_canon: string;
  group: string | null;
  ckey: string | null;
  dn: string | null;
  parent_nid: string | null;
  asm_key: string | null;
  attrs: JsonObject;
  geom_fp: string | null;
  status_flags: string[];
  provenance?: JsonObject;
};

/**
 * board 노드의 attrs(adapters/ecad — 길이는 mm, 없는 값은 null 이고 0 이 아니다). `outline_bbox` · `n_nets` · `odb_version` 은 2단계
 * (ODB 허브 OH-01 ~ OH-04 뒤) 칸이라 1단계에서는 늘 null 이다.
 */
export type EcadBoardAttrs = {
  board_id: string | null;
  name: string | null;
  revision: string | null;
  units: string | null;
  thickness: number | null;
  stackup_verdict: string | null;
  stackup_id: string | null;
  ecad_stackup_total: number | null;
  layer_count: number | null;
  n_components: number | null;
  n_components_placed: number | null;
  outline: { x_mm?: number | null; y_mm?: number | null; area_mm2?: number | null } | null;
  outline_bbox: JsonValue;
  n_nets: number | null;
  odb_version: string | null;
  source_hash: string | null;
};

/** rr_ir 엣지(definitions.edge) — 간극 · 관통 깊이 따위는 `attrs` 안에 있다. */
export type IrEdge = {
  eid: string;
  kind: string;
  kind_family: string;
  a: string;
  b: string | null;
  members?: string[];
  domain: string;
  status: string;
  attrs: {
    min_gap?: number | null;
    penetration_depth?: number | null;
    penetration_depth_is_lower_bound?: boolean;
    [key: string]: JsonValue | undefined;
  };
  provenance?: JsonObject;
};

export type IrWarning = {
  severity: "CRITICAL" | "WARNING" | "INFO";
  code: string;
  message: string;
  ref: string | null;
  source_kind: string | null;
};

/** 명명 치수(definitions.dim_named) — 값이 null 이면 `null_reason` 이 까닭이다. */
export type DimNamed = {
  name: string;
  value: number | null;
  unit: string | null;
  method: "measured" | "derived" | "declared" | (string & {});
  ref: string | string[] | null;
  formula: string | null;
  owner_sub?: string;
  null_reason: string | null;
};

/** 스냅샷 봉투의 소스 한 줄(definitions.source). ECAD 소스의 `stats` 는 보드 두께 · 적층 · 부품 수 따위다. */
export type IrSource = {
  kind: SourceKind | (string & {});
  app_key: string | null;
  adapter_version: string;
  channel: string | null;
  ref: JsonObject;
  source_hash: string | null;
  tol_config_hash?: string | null;
  scope?: JsonValue;
  stats?: JsonObject;
  app_version?: { version?: string | null; captured_via?: string | null; extra?: JsonValue } | null;
  degraded: string[];
  captured_at: number | null;
};

/**
 * `GET /snapshots/{id}?part=ir` — 동결된 rr_ir 원본 그대로(rr_ir.v1.json). `missing` 은 **bool 사전**이다(전에 글자 목록으로 적어
 * 두었다). 소스 종류 · 수는 `sources` 에서 센다(봉투에 kinds · counts 칸이 없다 — 그 칸을 읽어 화면이 백지였다).
 */
export type SnapshotIr = {
  ir_version: string;
  snapshot_id: string;
  project_id: string;
  owner_sub: string;
  label: string | null;
  captured_at: number;
  derived_from: string | null;
  partial: boolean;
  sources: IrSource[];
  primary_source: string | null;
  units: Record<string, string>;
  nodes: IrNode[];
  edges: IrEdge[];
  dims_named: DimNamed[];
  rollups: JsonObject;
  results: JsonObject | null;
  missing: Record<string, boolean>;
  warnings: IrWarning[];
  versions: { adapter_versions?: Record<string, string>; [key: string]: JsonValue | undefined };
  ir_hash: string;
};

/** 신호 한 칸(state.compute_signals · requirements.compute_req_signals) — 사전의 열쇠가 `sig:` 뒤의 이름이다. */
export type SignalRecord = {
  kind: string;
  value: JsonValue;
  unit: string | null;
  refs: string[];
  text: string;
  derived_from: string[];
  known: boolean;
};
export type CharacterSeed = { tag: string; rule: string; cites: string[]; text: string };

/** `sig:req.margin` 한 행(requirements.compute_req_signals) — 서버가 margin 오름차순으로 주고 미측정(known=false)은 맨 뒤다. */
export type ReqMarginRow = {
  name: string;
  op: string | null;
  limit: JsonValue;
  unit: string | null;
  actual: number | null;
  margin: number | null;
  rel: number | null;
  known: boolean;
  status: string;
};

/**
 * `GET /snapshots/{id}?part=state`(state.build_state — rr_state.v1.json). `gates` 와 `signals` 는 **사전**이다(전에 배열로 적어
 * 두어 스냅샷 화면이 `gates.some` 에서 백지였다).
 */
export type SnapshotState = {
  state_version: string;
  snapshot_id: string;
  ir_hash: string;
  project_id: string;
  rule_version: string;
  computed_at: number;
  blocked: boolean;
  gates: Gates;
  missing: Record<string, boolean>;
  signals: Record<string, SignalRecord>;
  character_seed: CharacterSeed[];
  feature_vector: JsonObject;
  rule_hits: RuleHit[];
  summary_text: string | null;
  summary_status: string;
};

/** 호출 로그 한 줄(ir_builder.load_calls — 응답 원문은 싣지 않는다). */
export type SnapshotCall = {
  call_id: string;
  seq: number;
  source_kind: string | null;
  app_key: string | null;
  channel: string | null;
  tool: string;
  args: JsonObject;
  ok: boolean;
  http_status: number | null;
  response_sha256: string | null;
  response_bytes: number | null;
  started_at: number | null;
  duration_ms: number | null;
  error: string | null;
};

/**
 * 규칙 적중 한 줄(state.evaluate_rules). `evaluable` 이 거짓이면 `pass` 는 null 이고 `not_evaluable_reason`(source_absent ·
 * degraded · truncated)이 까닭이다 — '이상 없음' 이 아니라 '평가 불가' 다. `found` 는 객체다(글자가 아니다).
 */
export type RuleHit = {
  rule: string;
  version: string;
  severity: Severity | string;
  pass: boolean | null;
  evaluable: boolean;
  not_evaluable_reason: string | null;
  found: { count: number; refs: string[]; text: string };
  why_it_matters: string;
  fix_hint: string;
  payload_hash?: string;
  refs: string[];
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
/** 요구 한 줄(requirements._public) — 받을 때는 `value_json` 이 아니라 푼 값 `value` 다(전에 value_json 을 읽어 늘 null 이었다). */
export type Requirement = {
  id: string;
  kind: RequirementKind;
  name: string;
  op: string | null;
  value: JsonValue;
  unit: string | null;
  source_ref: string | null;
  status: RequirementStatus;
  waive_reason: string | null;
  inherited_from: string | null;
  decided_by: string | null;
  decided_at: number | null;
};
export type RequirementList = { requirements: Requirement[] };

export type DimDefCreate = { name: string; kind: string; unit: string; extractor: string };
export type DimDef = DimDefCreate & { id: string; project_id: string; vocab_status: string };

// ── same-as · 원장 ────────────────────────────────────────────────────────────

/**
 * same-as 확인 행(sameas.review_rows) — pending · fuzzy 자동 · 충돌에 걸린 대응만 온다. `a` · `b` 는 nid, 원장 열쇠는
 * `a_stable` · `b_stable` 이다.
 */
export type SameAsPair = {
  id: string | null;
  scope: string | null;
  a: string;
  b: string;
  a_stable: string | null;
  b_stable: string | null;
  a_label: string | null;
  b_label: string | null;
  a_domain: string | null;
  b_domain: string | null;
  method: string;
  score: number;
  /** pending · auto(fuzzy) · confirmed · rejected — 화면은 모르는 값도 글자 그대로 보인다. */
  status: string;
  conflict: boolean;
  evidence: JsonValue;
};

export type SameAs = { pairs: SameAsPair[]; pending_n: number; G2: GateRecord | null };

/**
 * 대응 확정 · 거부 한 줄(sameas.record_decision) — 원장 열쇠는 노드 id(`a` · `b`)가 아니라 **stable 키**다. `pair_key` 는 scope 마다
 * 다르고(intra = project_id · pair = 두 project_id 를 정렬해 '|' 로 이은 것 · global = '-') 빠지면 400 `E100` 이다.
 */
export type SameAsPairDecision = {
  decision: "confirm" | "reject";
  scope: "intra" | "pair" | "global";
  a_stable: string;
  b_stable: string;
  pair_key: string;
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
/**
 * `POST /sameas/decide` 의 답(routes.post_sameas_decide — 배열은 한 트랜잭션이다). ckey 결정의 결과 줄은
 * `{ok, table: "rr_part_keys", decision, ckey, merged_into? | display_name? | status?}` 다. `G2` 는 지금 늘 null 이다.
 */
export type SameAsDecided = { updated: number; results: JsonObject[]; G2: GateRecord | null };

export type IfaceLedgerRow = {
  pair_key: string;
  kind_override: string | null;
  status: string;
  note: string | null;
};

// ── diff ─────────────────────────────────────────────────────────────────────

export type DiffCreate = { base_snapshot_id: string; target_snapshot_id: string };

/**
 * 쌍 비교의 ECAD 칸(diff.comparability — ecad-1031 §8). 쪽마다 present(보드를 온전히 실었다) · absent(보드 없음 · 읽지 않음) ·
 * failed(못 읽었거나 부분). 한쪽이라도 failed 면 `capture_partial`, 한쪽에만 보드가 실렸으면 `partial_scope` 이고 그때 ECAD 항목은
 * 남되 의미 사건을 만들지 않는다. `adapter_parity` 가 거짓이면 ECAD 항목 · 사건에만 caveat parser_differs 다.
 */
export type ComparabilityEcad = {
  base: "present" | "absent" | "failed" | (string & {});
  target: "present" | "absent" | "failed" | (string & {});
  excluded_reason: "capture_partial" | "partial_scope" | null | (string & {});
  adapter_parity: boolean;
};

/**
 * 쌍 비교의 비교 가능성(diff._comparability). 전에 `{ok, excluded_reason, note}` 로 적어 두어 '비교 가능' 배지가 늘 'no' 였다 —
 * 서버는 잣대마다 parity 를 주고 G7 이 그 요약이다. parity 의 null 은 '모름'(잴 입력이 없었다)이다.
 */
export type Comparability = {
  tol_parity: boolean | null;
  tol_keys_known: boolean;
  unit_parity: boolean;
  result_parity: boolean | null;
  result_present?: boolean;
  result_reason?: string | null;
  scope_parity: boolean;
  coordinate_ok: boolean;
  partial_any: boolean;
  ir_version_parity?: boolean;
  /** 소스 앱 판(system_status) — 공통 kind 가운데 하나라도 다르면 false, 모르면 null. */
  app_version_parity?: boolean | null;
  /** 어댑터(파서) 세대 — ecad 는 아래 `ecad.adapter_parity` 가 따로 본다. */
  adapter_parity?: boolean;
  source_schema_parity?: boolean;
  source_schema_drift_kinds?: string[];
  capture_parity?: boolean;
  primary_source_parity?: boolean;
  ecad?: ComparabilityEcad;
  G7: GateRecord;
  base_blocked: boolean;
  target_blocked: boolean;
};

/** `POST /diffs` 의 답(routes.create_diff) — 같은 쌍이 이미 있으면 그것이다. */
export type DiffCreated = {
  diff_id: string;
  counts: Record<string, JsonValue>;
  comparability: Comparability;
};

/**
 * 409 `gate_blocked` 의 본문(diff.check_pair_blocked) — 막힌 쪽(base · target)의 G6 레코드와 까닭(unit_mismatch · unit_unknown).
 * 오류 본문은 `{error, …detail}` 이라 이 칸들이 최상위에 펼쳐진다.
 */
export type DiffBlocked = { gates: { base?: GateRecord; target?: GateRecord }; reason: string };

export type DiffLayer = "structural" | "parametric" | "semantic";

/** 구조층 노드 변화(definitions.node_change). `domain` 이 ecad 면 ECAD 항목이다. */
export type DiffNodeChange = {
  cid: string;
  op: string;
  dn: string;
  nid_base: string | null;
  nid_target: string | null;
  ckey: string | null;
  label: string;
  kind: string;
  domain: string;
  correspondence_method: string | null;
  confidence: string;
  excluded_reason?: string | null;
  caveat?: string;
  text?: string;
};

/** 구조층 엣지 변화(definitions.edge_change). */
export type DiffEdgeChange = {
  cid: string;
  op: string;
  eid_base: string | null;
  eid_target: string | null;
  dn_a: string;
  dn_b: string | null;
  kind_family?: string;
  kind_from: string | null;
  kind_to: string | null;
  status_from: string | null;
  status_to: string | null;
  cross_file: boolean;
  excluded_reason: string | null;
  confidence: string;
  text?: string;
};

/** 파라메트릭 한 칸(definitions.param_item · result_item · material_item 을 화면이 읽는 칸만). */
export type DiffParam = {
  cid: string;
  dn?: string;
  eid?: string;
  name?: string;
  attr?: string;
  field?: string;
  metric?: string;
  before: JsonValue;
  after: JsonValue;
  delta?: number | null;
  rel_delta?: number | null;
  unit?: string | null;
  flag?: string;
  excluded_reason?: string | null;
  caveat?: string;
  text?: string;
};

/** 의미층 사건(definitions.event). */
export type DiffEventItem = {
  cid: string;
  code: string;
  change_kind: string;
  subject: { dns?: string[]; ckeys?: Array<string | null>; names?: string[] };
  subject_key: string;
  confidence: string;
  design_relevant: boolean;
  unconfirmed: boolean;
  excluded_reason: string | null;
  caveat?: string;
  text: string;
};

/** `GET /diffs/{id}?part=diff` — rr_diff 원본 그대로(rr_diff.v1.json). 전에 `items` 하나로 적어 두어 3층이 늘 비었다. */
export type DiffDoc = {
  diff_version: string;
  diff_id: string;
  project_id: string;
  pair_kind: "same_project_revision" | "cross_project" | null;
  base: { snapshot_id: string; ir_hash: string; label: string | null };
  target: { snapshot_id: string; ir_hash: string; label: string | null };
  comparability: Comparability;
  correspondence: { pending_n: number; method_counts: Record<string, number> };
  structural: { node_changes: DiffNodeChange[]; edge_changes: DiffEdgeChange[] };
  parametric: {
    node_params: DiffParam[];
    edge_params: DiffParam[];
    materials: DiffParam[];
    dims_delta: DiffParam[];
    result_delta: DiffParam[];
    rollup_delta: JsonObject[];
  };
  semantic: { blocked_by: string | null; events: DiffEventItem[] };
  stats: Record<string, JsonValue>;
  summary_text: string;
  summary_status: string;
  created_at: number;
};

/** `?part=summary` — `summary_text` 는 코드가 만든 원문이라 화면이 다시 쓰지 않는다. 줄은 글을 줄바꿈으로 나눈 것이다. */
export type DiffSummary = {
  diff_id: string;
  summary_text: string;
  summary_status: string;
  stats: Record<string, JsonValue>;
  comparability: Comparability;
  diff_hash: string | null;
  created_at: number;
};

/** `?part=events` 의 펼침 표 한 줄(rr_diff_events 열 그대로 — 0 · 1 은 SQLite 의 참거짓이다). */
export type DiffEventRow = {
  diff_id: string;
  cid: string;
  layer: string;
  code: string;
  change_kind: string | null;
  subject_key: string | null;
  ckeys_json: string | null;
  magnitude: number | null;
  unit: string | null;
  rel: number | null;
  confidence: string | null;
  design_relevant: number;
  unconfirmed: number;
  excluded_reason: string | null;
  text: string;
};
export type DiffEvents = { diff_id: string; events: DiffEventRow[] };

/** `GET /precedents?diff_id=` 의 답(brief.precedents) — 변화 종류별 선례 수치와 같은 주체의 등록부 행. */
export type Precedents = {
  delta_priors: Array<{
    change_kind: string;
    mechanism: string | null;
    mechanism_detail: string | null;
    n_raised: number;
    n_targets: number;
    n_verified: number;
    n_dismissed: number;
  }>;
  clusters: Array<{
    reg_ref: string;
    target_key: string;
    project_code: string | null;
    cluster_key: string;
    subject_names: JsonValue;
    severity: string | null;
    status: string;
    support: number | null;
    claim: string | null;
    path: JsonValue;
  }>;
  rule_hits: RuleHit[];
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

/**
 * 패널 잡 본문(`POST /targets/{key}/jobs` 의 mode 기본 panels — routes.JobBody). `mode` 는 싣지 않는다(기본이 panels 다).
 * 판단 LLM 두 칸은 Claude 를 골랐을 때만 싣는다 — GLM 잡의 본문은 이 칸이 생기기 전과 바이트로 같다.
 */
export type TargetJobCreate = {
  tier: Tier;
  concurrency?: number;
  modifiers?: string[];
  user_memo?: string;
  consent?: boolean;
  /** 판단 LLM — 없으면 GLM(이 박스의 LLM)이다. */
  llm?: "claude";
  /** 반출 동의 — 사람이 경고를 보고 체크했을 때만. JSON true 만 받는다(글자 'true'·1 은 거절된다). */
  consent_external?: true;
};

/**
 * Claude 잡의 반출 동의 기록(runner.llm_params) — 누가 · 언제 · 어느 입구로(web · mcp · api). 잡을 만들 때 셋 다 적히지만,
 * 진행판은 잡 params 의 기록을 그대로 옮기므로(`dict(consent or {})`) 기록이 없으면 빈 객체다 — 칸마다 없을 수 있다.
 */
export type ConsentExternal = { by?: string | null; at?: number | null; source?: string | null };

/** `POST /targets/{key}/jobs` 패널 잡의 답(runner.create_job). */
export type TargetJobCreated = {
  job_id: string;
  panels_planned: number;
  /** 호출 수 어림의 아래 · 위(planner.tier_plan 의 llm_calls_low · llm_calls_high). */
  llm_calls_estimate: { low: number; high: number };
  credential: Credential;
  credential_email: string | null;
  /** 등록한 PAT 가 있는데 수명 때문에 다른 사람 자격으로 돈다 — 그 까닭. */
  credential_note?: string;
  /** 메모가 브리프 M 상한을 넘어 좌석이 앞부분만 받는다 — 원문 길이와 실린 길이. */
  user_memo_cut?: { chars: number; kept: number };
  /** Claude 로 고른 잡에만 있다(GLM 잡의 답은 이 칸이 없다). */
  llm?: "claude";
  consent_external?: ConsentExternal;
};

export type JobStateResponse = { state: BatchJobState };

/**
 * 도는 패널의 마지막 신호(routes._live_signal) — 그 패널이 지금 도는 동안에만 온다. `*_idle_s` 는 서버 시계로 잰 초다.
 * 러너가 1분 간격으로 적으므로 건강한 패널도 `frame_idle_s` 가 80초 안팎까지 간다.
 */
export type JobSignal = {
  panel_id: string;
  panel_no: number | null;
  started_at: number;
  last_frame_at: number | null;
  last_event_at: number | null;
  last_step: string;
  frames: number;
  frame_idle_s: number | null;
  event_idle_s: number | null;
  advice?: string;
};

/**
 * 진행판의 패널 잡(`GET /targets/{key}/coverage` 의 `job` — routes.coverage_payload). 카드 대조 검토 잡은 `review` 칸이 맡는다.
 * Claude 잡이면 `llm` · `consent_external`(· `llm_mismatch`)이 붙고 GLM 잡은 그 칸이 없다.
 */
export type CoverageJob = {
  id: string;
  tier: Tier;
  state: BatchJobState;
  /** rr_jobs.pause_reason CHECK — 사람(user) · 수확 체감(diminishing) · 하루 상한(daily_cap). */
  pause_reason: "diminishing" | "daily_cap" | "user" | null;
  panels_done: number;
  panels_total: number;
  error: string | null;
  signal: JobSignal | null;
  llm?: "claude";
  consent_external?: ConsentExternal;
  /** Claude 잡인데 외부 응답자 답이 아니었던 호출 · 패널 수. */
  llm_mismatch?: number;
} | null;

/**
 * 카드 대조 검토 잡의 일꾼 한 명(routes._review_job_payload — 도는 호출마다의 마지막 신호). `*_idle_s` 는 서버 시계로 잰 초다.
 */
export type ReviewWorkerSignal = {
  agent_key?: string;
  purpose?: string;
  unit_id?: string | null;
  call_kind?: string;
  started_at?: number | null;
  last_frame_at: number | null;
  last_event_at: number | null;
  last_step?: string;
  frame_idle_s: number | null;
  event_idle_s: number | null;
};

// ── 카드 대조 검토(재설계 M2 · M3 — 포털 docs/risk-review-redesign/m3-frontend-request.md) ─────────────────

/** 셀 상태(review_cells.CELL_STATES) — 화면은 na_irrelevant 를 '거름', no_input 을 '입력 결손 — 판정 못 함' 으로 보인다(이름은 그대로). */
export type CellState = "pending" | "running" | "reviewed" | "na_irrelevant" | "no_input" | "failed" | "skipped";
/** 검토한 셀을 무엇으로 봤나(review_cells.CELL_BASES). */
export type CellBasis = "cards" | "background" | "role_only" | "search_only" | "noinput";
/** 거르기 분류의 길 — 셀 목록의 `route` 쿼리와 같은 어휘다. */
export type CellRoute = "review" | "filtered" | "audit" | "noinput";
/** 전문가 머리 상태(review_cells.EXPERT_STATES). */
export type ExpertState = "planned" | "running" | "ready" | "partial" | "blocked";

/** 품질 블록의 비율 하나(review_quality.rate) — den 이 표본 바닥 미만이면 value 가 null 이다(0 이 아니다). */
export type RateMetric = {
  value: number | null;
  num: number;
  den: number;
  upper95?: number | null;
  min_n?: number;
  threshold?: JsonObject;
  within?: boolean | null;
};

/** 셀 셈(review_cells.review_summary — 활성 단위만). */
export type ReviewCellCounts = {
  total: number;
  by_state: Record<CellState, number>;
  /** reviewed 셀의 바탕 — 어휘 밖 값은 unset 으로 센다(있을 때만 온다). */
  by_basis: Record<CellBasis, number> & { unset?: number };
  /** 가장 최근 검토 잡이 찍은 셀(잡이 없으면 null). */
  in_scope: { job_id: string; total: number; by_state: Record<CellState, number> } | null;
  out_of_scope_pending: number;
  /** 사람이 처분하지 않은 failed 셀. */
  failed_open: number;
};

/** 진행판 review.cells — 셀 셈에 품질 블록이 센 '형식만 채운 칸'(품질을 아직 세지 않았으면 null)을 더한다. */
export type ReviewCellsSummary = ReviewCellCounts & { form_only: RateMetric | null };

export type ReviewExpertsSummary = { total: number; by_state: Record<ExpertState, number> };

/** 검토 순서 한 줄(routes.review_order_payload — planner.review_order + 머리 상태 · 얼린 묶음의 카드 수). */
export type ReviewOrderRow = {
  order: number;
  agent_key: string;
  domain: string;
  rank_in_domain: number | null;
  tier: Tier;
  deferred: boolean;
  /** ECAD 에 기대는데 ECAD 가 없다(ecad_absent) · 넷 · 배치가 필요하다(ecad_nets_deferred). */
  input_gaps: string[];
  state: ExpertState | null;
  cards_total: number | null;
  checkable_n: number | null;
};

/** 진행판 review.quality(routes._quality_summary) — 문면과 기준 밖 항목. 수치는 문면 줄에 있다. */
export type ReviewQualitySummary = {
  job_id: string | null;
  computed_at: number | null;
  title: string | null;
  text: string | null;
  policy_version: string | null;
  ledger_hash: string | null;
  out_of_bounds: string[];
  unchecked: string[];
};

/** 거른 셀 표본(review_cells.closure_cells 의 filtered.audit 가운데 진행판이 싣는 칸). upper95 는 0~1, 표본이 없으면 null. */
export type ReviewFilterAudit = {
  risk_miss: number;
  relevance_miss: number;
  undetermined: number;
  kept: number;
  upper95: number | null;
  upper95_conservative: number | null;
  n_audit: number;
  floor_met: boolean;
  pending: number;
};

/** 진행판 review.filter(재설계 M3 C3-8) — mode · approved 는 가장 최근 검토 잡이 얼린 값이다(잡이 없으면 off · null). */
export type ReviewFilter = {
  mode: "off" | "shadow" | "on" | (string & {});
  /** 배정표 승인 문 — false 면 아무 셀도 걸러지지 않는다. 검토 잡 전에는 null. */
  approved: boolean | null;
  would_filter: number;
  filtered: number;
  audited: number;
  audit: ReviewFilterAudit;
  shadow: { would_filter: number; sampled: number; risk_miss: number; upper95: number | null };
  widened: string[];
  off: boolean;
  /** 거른 셀이 아낀 호출의 어림. */
  saved_calls_est: number;
};

/** 입력 결손(재설계 M3 C3-3) — 판정 대신 두 질문으로 닫힌 셀의 셈. */
export type ReviewNoInput = {
  experts: number;
  cells: number;
  by_outcome: { impact: number; unknown: number; request: number; none: number };
};

/** 다시 연 셀의 몫(review_runner.reopen_budget — 진행판 review.job.progress.reopened_extra). */
export type ReopenedExtra = {
  cells: number;
  runs: number;
  calls_est: number;
  consented: { cells: number; calls_est: number };
  unconsented: { cells: number; calls_est: number };
  allowance: number;
  /** 잡을 만들 때 동의받은 추정(calls_estimate.expected — 거르기 없음 가정). */
  expected: number;
  max_calls: number;
  hold: "consent_extra" | "max_calls" | null;
};

/** 검토 잡의 호출 셈(rr_review_calls 상태별) — 진행판을 아직 세지 않았으면 칸이 비어 있을 수 있다. */
export type ReviewCalls = {
  ok: number;
  infra_fail: number;
  content_fail: number;
  wait: number;
  aborted: number;
  last_ok_at: number | null;
  avg_ok_s: number | null;
};

/**
 * 검토 잡의 진행판(routes._review_job_payload 가 progress_json 에서 옮긴 칸). 막 선 잡은 진행판을 아직 세지 않아 칸이 null 이거나
 * 빈 객체다 — 칸마다 없을 수 있다(0 으로 읽지 않는다).
 */
export type ReviewJobProgress = {
  packs: Partial<{ total: number; todo: number; ok: number; empty: number; error: number; blocked: number }> | null;
  experts: Partial<ReviewExpertsSummary> | null;
  cells: Partial<ReviewCellCounts & { failed: number }> | null;
  calls: Partial<ReviewCalls> | null;
  breaker: Partial<{ state: string; trips: number; hold_until: number | null; since: number | null }> | null;
  server: JsonObject | null;
  reopened_extra: ReopenedExtra;
};

/** 기다림(잡은 running 이고 보류가 아니다) — health_unknown · draining 은 note 에 백엔드 문장이 있다. */
export type ReviewWaiting = {
  reason: string;
  since?: number | null;
  retry_at?: number | null;
  note?: string;
  source?: string;
};

/** 검토 잡 범위(정규 표기 — 칸끼리 AND, 빠진 칸은 전부). */
export type ReviewScope = { tiers?: string[]; domains?: string[]; agents?: string[]; unit_ids?: string[] };

/** 진행판의 검토 잡 한 줄(routes._review_job_payload). Claude 잡이면 `llm` · `consent_external`(· `llm_mismatch`)이 붙는다. */
export type ReviewJob = {
  id: string;
  mode: "reviews";
  state: BatchJobState;
  /** 보류 코드(review_ops.HOLD_CODES) — consent_extra · max_calls 는 자동 재개가 없다. */
  hold_code: string | null;
  hold_until: number | null;
  hold_n: number;
  error: string | null;
  credential_email: string | null;
  scope: ReviewScope;
  llm?: "claude";
  consent_external?: ConsentExternal;
  llm_mismatch?: number;
  /** live(근거 꾸러미 실호출) → pack → review, 끝나면 그 상태 이름. 진행판 전이면 null. */
  phase: string | null;
  progress: ReviewJobProgress;
  waiting: ReviewWaiting | null;
  /** 도는 호출마다의 마지막 신호 — 끝난 잡은 null. */
  signal: { workers: ReviewWorkerSignal[] } | null;
};

/** 진행판의 카드 대조 검토 칸(routes.review_payload) — 셀 원장이 없는 패널 대상은 null 이다. */
export type CoverageReview = {
  units: number;
  cells: ReviewCellsSummary;
  experts: ReviewExpertsSummary;
  /** 카드 폭포(품질 블록 json.cards) — 이 화면은 그리지 않는다. */
  cards: JsonObject | null;
  quality: ReviewQualitySummary | null;
  order: ReviewOrderRow[];
  dispositions: { retried: number; skipped: number };
  filter: ReviewFilter;
  noinput: ReviewNoInput;
  job: ReviewJob | null;
};

/** 완결 잔여 낱말(closure.RESIDUAL_ITEMS — 응답의 차례 그대로). */
export type QualifierItem =
  | "input_gap"
  | "failed"
  | "skipped"
  | "issues_untried"
  | "issues_reraised"
  | "filtered"
  | "unit_excluded"
  | "quality"
  | "undetermined"
  | "no_cards"
  | "depth_no_cards"
  | "cross_not_run"
  | "mech_not_run";

export type AckState = "valid" | "stale" | "revoked";

/**
 * 완결 잔여 한 줄(closure.residuals + 확인 표기). `blocking` 이고 `acked` 가 아니면 저장 레벨이 오르지 않는다. 낱말마다 더 실리는
 * 칸은 그 낱말에만 있다.
 */
export type Qualifier = {
  item: QualifierItem | (string & {});
  n: number;
  label: string;
  blocking: boolean;
  acked: boolean;
  basis_n: number;
  basis_hash: string;
  ack?: { state: AckState; by: string; at: number; reason: string };
  experts?: number;
  domains?: string[];
  by_code?: Record<string, number>;
  crowded?: string[];
  p1?: number;
  held_fail?: number;
  sentences?: string[];
  issue_ids?: string[];
  audit?: JsonObject;
  off?: boolean;
  by_reason?: Record<string, number>;
  others?: Record<string, number>;
  out_of_bounds?: string[];
  strong_ratio_cells?: number | null;
  of?: number;
  ratio?: number;
  mixed?: Record<string, number>;
  pairs?: number;
};

/** 사슬 단계(routes.chain_stage) — 살아 있는(없으면 마지막) 쟁점 · 종합 잡. */
export type ChainStage = {
  mode: "issues" | "synth";
  job_id: string;
  state: BatchJobState;
  hold_code: string | null;
  pause_reason: string | null;
  /** `pat_unavailable:` · `restart:` · `draining:` 로 시작하면 그 뜻이다(요청서 1절). */
  error: string | null;
  advice?: string;
  llm?: "claude";
  consent_external?: ConsentExternal;
  llm_mismatch?: number;
};

export type ReportTrigger =
  | "reviews_partial"
  | "reviews_closed"
  | "issues_closed"
  | "synth_done"
  | "ack"
  | "manual"
  | "level_up";
export type NarrativeState = "none" | "partial" | "full";

/** 마지막 종합 보고서 판의 머리(routes.report_head). */
export type ReportHead = {
  version_no: number;
  trigger: ReportTrigger | (string & {});
  narrative_state: NarrativeState | (string & {});
  created_at: number;
};

/** 검토 단위 목록 한 줄(units.manifest) — 단위 행을 들여오지 않은 박스는 `row_absent` 만 있다. */
export type UnitManifestItem = {
  unit_id: string;
  seq: number;
  row_absent?: true;
  kind?: string;
  reviewable?: boolean;
  title?: string;
  n_changes?: number;
};
/** `GET /targets/{key}/units` — 단위가 없는 대상은 status none · units []. */
export type UnitManifest = {
  target_key: string;
  flow: "panels" | "cells";
  status: string;
  total: number;
  offset: number;
  returned: number;
  next_offset?: number;
  units: UnitManifestItem[];
};

/** 검토 단위 빌드 한 줄(units.summary_of). */
export type UnitsSummary =
  | { rev: number; status: string; reviewable_n: number }
  | { rev: number; status: string; error: string | null }
  | { status: "none" };

export type Coverage = {
  target_key: string;
  job: CoverageJob;
  /** 셀 원장이 있는 대상만 객체다(패널 대상은 null). */
  review: CoverageReview | null;
  roster_size: number;
  /** 도메인 코드 → 커버리지 상태별 좌석 수. */
  by_domain: Record<string, Partial<Record<CoverageStatus, number>>>;
  /** 전체 합계(도메인을 가로지른 상태별 수). */
  by_status: Partial<Record<CoverageStatus, number>>;
  /** strong 비율(planner.coverage_summary) — done · done_weak 좌석 수와 그 비(분모 0 이면 null). 전에 number 로 적혀 있었다(견본이 잡았다). */
  strong: { done: number; done_weak: number; ratio: number | null };
  unseated_n: number;
  level: CoverageLevel;
  close_level: CloseLevel;
  /** 심사 방식 — panels(Tier 패널) · cells(카드 대조). */
  flow: "panels" | "cells";
  units: UnitsSummary;
  /** RA · AIDataHub 반영 요약 — 재동기를 누르기 전에도 늘 온다(보내는 쪽이 아직 없다는 것까지 message 가 말한다). */
  external_sync: ExternalSync;
  /** 아래 넷은 카드 대조 대상(flow cells)만 싣는다 — 패널 대상의 응답에는 칸이 없다. 완결 표기 "<레벨>(<막힌 까닭 · 잔여>)". */
  level_label?: string;
  qualifiers?: Qualifier[];
  stage?: ChainStage | null;
  report?: ReportHead | null;
};

// ── 검토 잡 만들기 · 셀 처분(M3 3절) ─────────────────────────────────────────

/** 검토 잡 본문(`POST /targets/{key}/jobs` mode reviews) — 패널 칸(tier · modifiers · concurrency)을 실으면 422 다. */
export type ReviewJobCreate = { mode: "reviews"; scope?: ReviewScope; user_memo?: string; consent?: true };

/** 호출 수 추정 — 동의 문턱 · 상한은 expected(거르기 없음 가정)와 견준다. */
export type CallsEstimate = { low: number; expected: number; high: number; basis: string };

/** `POST /targets/{key}/jobs` 검토 잡의 답(review_runner.create_review_job). */
export type ReviewJobCreated = {
  job_id: string;
  mode: "reviews";
  cells_total: number;
  cells_in_scope: number;
  experts_in_scope: number;
  units: number;
  calls_estimate: CallsEstimate;
  credential: { kind: "requester" | "owner"; email: string; exp: number };
  /** 범위 안에서 저절로 풀린 보류 좌석 수. */
  undeferred: number;
  credential_note?: string;
  llm?: "claude";
  consent_external?: ConsentExternal;
};

/** 처분할 셀 — 쌍 목록과 거름 가운데 정확히 하나(review_cells.select_cells). */
export type CellsFilter = {
  job_id?: string;
  agent_key?: string;
  unit_id?: string;
  domain?: string;
  error_code?: string;
  state?: CellState;
};
export type CellsSelector = { cells: Array<[string, string]> } | { filter: CellsFilter };

export type CellsRetryBody = CellsSelector & { reason?: string; force?: true; start?: false; consent?: true };
export type CellsSkipBody = CellsSelector & { reason: string };

/** 처분이 그 셀을 집을 잡에 한 일(review_runner.dispose_cells 의 job). */
export type DisposeJob = {
  action: "created" | "adopted" | "waiting" | "none";
  job_id?: string;
  calls_estimate?: CallsEstimate;
  adopted?: number;
  waiting?: number;
  /** 살아 있는 잡에 얹은 셀 몫 때문에 그 잡이 멈췄다. */
  hold?: "consent_extra" | "max_calls";
  /** 넘김으로 몫이 여유 안으로 돌아와 그 잡이 이어 돈다. */
  resumed?: boolean;
};

/** 다시 · 넘김의 답 — 넘김은 걸림 셈(hits · hits_by · hits_basis · hits_note?)을 더한다. */
export type CellsDisposed = {
  target_key: string;
  matched: number;
  retried?: number;
  skipped?: number;
  not_failed: number;
  keys_total: number;
  keys: Array<[string, string]>;
  experts: number;
  changed: boolean;
  audit_id: string | null;
  job: DisposeJob;
  hits?: number | null;
  hits_by?: { card: number; offcard: number; noinput: number } | null;
  hits_basis?: "members" | "pack_missing";
  hits_note?: string;
};

/** 셀 목록 한 행(routes.cells_payload — rr_review_cells 열 이름 그대로, 선점 · JSON 열은 빠진다)에 거른 까닭 한 줄. */
export type ReviewCellRow = {
  target_key: string;
  unit_id: string;
  agent_key: string;
  domain: string;
  unit_seq: number;
  state: CellState;
  route: CellRoute | (string & {}) | null;
  /** 거르지 않은 까닭 — rank1 · global_unit · no_cards · input_gap · widened · filter_off · handoff · human_retry · … */
  route_forced: string | null;
  basis: CellBasis | (string & {}) | null;
  run_id: string | null;
  tries: number;
  charged: number;
  error_code: string | null;
  error: string | null;
  cards_expected: number | null;
  cards_judged: number | null;
  n_fail: number;
  n_warning: number;
  n_undetermined: number;
  n_offcard: number;
  truncated: number | null;
  status_source: "code" | "human";
  decided_by: string | null;
  decided_at: number | null;
  decide_note: string | null;
  reopened_n: number;
  updated_at: number | null;
  /** 두 신호가 다 무관이라 거른(거를 수 있던) 셀만 한 줄, 아니면 null. «» 안은 위생 처리한 LLM 글이다. */
  filter_reason: string | null;
};

export type CellList = {
  target_key: string;
  total: number;
  limit: number;
  offset: number;
  next_offset?: number;
  rows: ReviewCellRow[];
};

/** `POST /targets/{key}/undefer`(패널 대상) — 저장된 레벨은 내려가지 않는다(depth 가 지금의 깊이). */
export type Undeferred = {
  target_key: string;
  undeferred: number;
  agents: string[];
  agents_total: number;
  changed: boolean;
  level: CoverageLevel;
  note: string;
  /** 영역마다 지금의 깊이 — 패널 대상은 {need, have, roster, deferred}(registry._close_level_panels). */
  depth: Record<string, { need: number; have: number; roster?: number; deferred?: number }> | null;
};

// ── 전문가 보고서 · 종합 보고서 쪽(M2 3-7 · M3 5절) ─────────────────────────

/** 보고서 쪽 하나 — 블록 넷 가운데 하나만 차 있고, 값은 마크다운 조각 배열이다(조각 안에 줄바꿈이 있을 수 있다). */
export type ReportPage = {
  page_no: number;
  kind: string;
  title: string;
  blocks: { background: string[]; results: string[]; recommendation: string[]; minutes: string[] };
};

export type ExpertHead = {
  agent_key: string;
  domain: string;
  rank_in_domain: number | null;
  tier: string | null;
  review_order: number | null;
  state: ExpertState;
  run_id: string | null;
  pack_status: string;
  pack_error: string | null;
  /** cards · background · none — 묶음 전이면 null. */
  card_basis: string | null;
  sweep_state: string;
  cells_total: number;
  revision: number;
  findings_n: number | null;
  coverage_status: string | null;
  error: string | null;
  finalized_at: number | null;
  /** 얼린 묶음의 카드 수 — 묶음 전이면 null. */
  cards: { cards_total: number; checkable_n: number; background_n: number; unrenderable_n: number } | null;
  cells: { total: number; by_state: Record<CellState, number> };
};
export type ExpertList = { target_key: string; total: number; experts: ExpertHead[] };

export type ExpertReportPart = "summary" | "units" | "cards" | "full";
/** 전문가 보고서 쪽(routes.expert_report_envelope). `version` 은 마감 판(revision)이다. */
export type ExpertReportPage = {
  target_key: string;
  agent_key: string;
  state: ExpertState;
  version: number;
  report_hash: string | null;
  finalized_at: number | null;
  coverage_status: string | null;
  opinion_id: string | null;
  review_id: string | null;
  /** 막힌 전문가(blocked)의 까닭 — 앞 보고서는 덮지 않는다. */
  state_why: string | null;
  format: "md";
  part: ExpertReportPart;
  unit_id: string | null;
  pages_total: number;
  page_no: number;
  next_page?: number;
  page: ReportPage;
};

export type SynthPart = "summary" | "domains" | "mechanisms" | "appendix" | "full";
/** 종합 보고서 쪽(routes.report_envelope) — 머리는 쪽마다 같다. `version` 은 고르는 칸이 아니라 대조 칸이다. */
export type SynthReportPage = {
  target_key: string;
  version: number;
  report_uid: string;
  title: string;
  level_label: string;
  narrative_state: NarrativeState | (string & {});
  trigger: ReportTrigger | (string & {});
  counts: JsonObject;
  created_at: number;
  format: "md";
  part: SynthPart;
  pages_total: number;
  page_no: number;
  next_page?: number;
  page: ReportPage;
};

/** `POST /targets/{key}/report {refresh_summaries:false}` — 코드 조립 판(같은 내용이면 created false 로 그 판). */
export type ReportAssembled = {
  target_key: string;
  report_uid: string;
  version_no: number;
  pages_n: number;
  level_label: string;
  counts: JsonObject;
  narrative_state: NarrativeState | (string & {});
  created: boolean;
};
/** `POST /targets/{key}/report {refresh_summaries:true}` — 종합 잡(같은 길의 대기 잡이 있으면 그 잡, created false). */
export type SynthJobCreated = {
  target_key: string;
  job_id: string;
  created: boolean;
  credential: string | null;
  /** 사용자 PAT 가 없으면 잡은 서고 `pat_unavailable: …` 가 실린다(등록하면 집힌다). */
  error?: string;
  llm: "glm" | "claude";
  consent_external?: ConsentExternal;
};

// ── 쟁점(M3 4절) ────────────────────────────────────────────────────────────

export type IssueState =
  | "queued"
  | "planned"
  | "running"
  | "resolved"
  | "inconclusive"
  | "untried_cap"
  | "withdrawn"
  | "skipped";
export type IssueOutcome = "upheld" | "downgraded" | "escalated" | "rejected" | "undetermined";

/** 패널이 판정한 뒤 근거가 바뀐 쟁점(routes._reargue_out) — 새 패널이 정할 때까지 옛 판정이 보인다. */
export type IssueReargue = {
  label: string;
  at: number;
  round: number;
  basis_hash: string;
  panel_basis_hash: string;
  raisers_added: string[];
  raisers_removed: string[];
  opposers_added: string[];
  opposers_removed: string[];
  claimed_before: JsonObject;
  claimed_after: JsonObject;
  /** 새 패널이 결정을 못 냈다 — 그 패널과 까닭. */
  new_panel_failed?: { panel_id: string; reason: string; at: number };
};

export type IssueRow = {
  issue_id: string;
  rank: number | null;
  types: string[];
  p_class: "P1" | "P2" | "P3" | (string & {});
  priority: number;
  anchor_cluster_key: string;
  unit_id: string | null;
  state: IssueState | (string & {});
  state_reason: string | null;
  outcome: IssueOutcome | (string & {}) | null;
  outcome_json: {
    panel_id?: string;
    atom_finding_ids?: string[];
    severity_after?: string | null;
    judgement_after?: string | null;
    grade_after?: string | null;
    contest_note?: string;
  } | null;
  distribution: {
    raisers: number;
    raisers_by_domain: Record<string, number>;
    by_judgement_claimed: Record<string, number>;
    by_severity: Record<string, number>;
    opposers: number;
  };
  panel_id: string | null;
  seats: Array<{ key: string | null; domain: string | null; issue_role: string | null }>;
  selected_round: number | null;
  attempts: number;
  charged: number;
  reargue: IssueReargue | null;
};

export type IssueList = {
  target_key: string;
  total: number;
  limit: number;
  offset: number;
  next_offset?: number;
  /** 거른 목록 전체의 지문 — 앞 쪽과 다르면 그사이 원장이 바뀐 것이라 offset 0 부터 다시 받는다. */
  ledger_rev: string;
  cap: { base: number; hard: number; run: number };
  rows: IssueRow[];
};
export type IssueAction = { action: "queue" | "skip"; reason: string };
export type IssueActed = { issue_id: string; state: "queued" | "skipped"; job_id: string | null };

// ── 완결과 확인(M3 6절) ─────────────────────────────────────────────────────

/** 영역 깊이 — 분모는 카드로 본 전문가다. 카드 없는 영역은 exempt no_cards(막지 않고 표기 잔여). */
export type DepthRow = { active: number; have: number; need: number; cardless: number; exempt?: "no_cards" };

export type CloseAck = {
  item: string;
  ack_at: number;
  ack_by: string;
  ack_reason: string;
  basis_n: number;
  basis_hash: string;
  revoked_by: string | null;
  revoked_at: number | null;
  state: AckState;
};

/** 완결 판정의 수(closure.cell_counts — 밑줄 칸은 빠진다). 화면이 읽는 칸만 적었다. */
export type ClosureCounts = {
  roster: number;
  units: { reviewable: number; excluded_by_reason: Record<string, number>; unassigned: number };
  cells: {
    expected: number;
    actual: number;
    by_state: Record<string, number>;
    reviewed_by_basis: Record<string, number>;
    verdict_gaps: number;
  };
  experts: { reports: { expected: number; ready: number; partial: number; blocked: number; missing: number } };
  issues: {
    by_state: Record<string, number>;
    by_outcome: Record<string, number>;
    open: number;
    cap: { base: number; hard: number };
  };
  registry: { clusters: number; attention: { A: number; B: number; C: number; D: number }; card_fail_claimed: number };
  handoffs: { lines: number; pairs: number };
  invariants: string[];
};

/** `GET /targets/{key}/closure` — 카드 대조 대상(closure.close_level_cells 캐시 + 확인 목록). */
export type ClosureCells = {
  target_key: string;
  flow: "cells";
  level: CoverageLevel;
  previous_level: CoverageLevel;
  raised: boolean;
  close_level: CloseLevel;
  /** 지금 계산한 레벨 — 저장 레벨(level)은 내려가지 않는다. */
  level_current: CoverageLevel;
  regressed: boolean;
  level_label: string;
  c1: boolean;
  c2: boolean;
  c3: boolean;
  qualifiers: Qualifier[];
  counts: ClosureCounts;
  roster_size: number;
  status_counts: Record<string, number>;
  unseated_n: number;
  detail: {
    depth: Record<string, DepthRow>;
    strong_ratio_cells: number | null;
    skipped_ratio: number;
    cells_hash: string;
    fresh: {
      issues: boolean;
      report: boolean;
      report_version: number | null;
      synth_version: number | null;
      selected: boolean;
      reopened_since: number | null;
    };
  };
  acks: CloseAck[];
};
/** 패널 대상의 같은 경로 — 패널 판정(registry._close_level_panels)에 flow 가 붙는다. 확인 길은 없다. */
export type ClosurePanels = {
  target_key: string;
  flow: "panels";
  level: CoverageLevel;
  close_level: CloseLevel;
  c1: boolean;
  c2: boolean;
  c3: boolean;
  detail: JsonObject;
};
export type Closure = ClosureCells | ClosurePanels;

/** 확인 · 확인 취소의 답 — 둘 다 보고서 판(trigger ack)을 세우고 그 번호(같은 내용이면 앞 판, 조립 실패면 null)를 돌려준다. */
export type CloseAcked = {
  item: string;
  ack_at: number;
  ack_by: string;
  basis_hash: string;
  basis_n: number;
  level: CoverageLevel;
  level_label: string;
  report_version: number | null;
};
export type CloseAckRevoked = {
  item: string;
  revoked_by: string;
  revoked_at: number;
  level: CoverageLevel;
  level_label: string;
  report_version: number | null;
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

/**
 * 좌석을 사람이 옮긴다(`PUT /targets/{key}/coverage/{agent_key}` — routes.put_coverage). skipped 는 사유가 필수이고(빈 사유는 422
 * E100), pending 은 carried 되돌리기다. 허용되지 않는 전이는 409 E100 이다(planner.ALLOWED_TRANSITIONS).
 */
export type SeatUpdate = { status: "skipped" | "pending"; reason?: string };
export type SeatUpdated = {
  target_key: string;
  agent_key: string;
  status: CoverageStatus;
  reason?: string;
  cycle?: number;
  status_source: "human" | "code";
  decided_by: string | null;
  decided_at: number | null;
};

// ── 등록부 · verdict ─────────────────────────────────────────────────────────

/** 등록부 행의 카드 · 근거 인용(merged.cites) — 카드 인용은 판정당 200자이고 줄였으면 원래 길이가 quote_chars 에 있다. */
export type Cite = { ref: string; quote: string; quote_chars?: number };

/** 전문가 수로 센 주장값(cells 대상 — hold 가 등록부를 WARNING · 중대로 묶어도 원래 주장). */
export type RegistryClaimed = {
  judgement: Judgement | (string & {}) | null;
  severity: Severity | (string & {}) | null;
  sev3: number | null;
  fail_experts: number;
  critical_experts: number;
  verified_fail_experts: number;
};
export type RegistryDistribution = {
  by_judgement_claimed: Record<string, number>;
  by_severity: Record<string, number>;
  raisers_by_domain: Record<string, number>;
};

/**
 * 등록부 행의 병합 본문(registry._merge_cluster 의 merged — REST 가 merged_json 을 풀어 싣는다). 옛 행 · 패널만 본 비교 보기에는 칸이
 * 없을 수 있어 칸마다 선택이다. claimed · distribution · unit_ids · before_issue · issue_reraised 는 cells 대상만 있다.
 */
export type RegistryMerged = {
  cluster_key?: string;
  stored_cluster_key?: string;
  direction?: string;
  claim?: string;
  claim_finding_id?: string;
  warrant?: string;
  /** 들여온 카드 대조 근거 문장의 원래 길이(줄였을 때). */
  warrant_chars?: number;
  severity_counts?: Record<string, number>;
  precedent_counts?: Record<string, number>;
  feature_snapshot?: JsonObject;
  /** 쟁점 우선순위가 같은 가중을 쓴다(cells 대상). */
  w_det?: number;
  raised_by?: string[];
  domains?: string[];
  owner_domain?: string;
  names?: string[];
  cites?: Cite[];
  member_ids?: string[];
  rejected_refs?: string[];
  human_refs?: string[];
  panels?: string[];
  contest_notes?: Array<{ finding_id: string; by: string[]; note: string }>;
  resolving_checks?: string[];
  trigger_condition?: string;
  claimed?: RegistryClaimed;
  distribution?: RegistryDistribution;
  unit_ids?: string[];
  /** 쟁점 패널이 행을 덮기 전 값 — 덮였을 때만(D-34 '덮되 분포를 남긴다'). */
  before_issue?: {
    severity: string;
    sev3: number;
    judgement: string;
    evidence_grade: string;
    claimed: RegistryClaimed | null;
    distribution: RegistryDistribution | null;
    support_experts: number | null;
    support_domains: number | null;
    support_units: number | null;
    support_verified: number | null;
  };
  /** 패널이 판정한 뒤 근거가 바뀐 쟁점의 표기(쟁점 행의 reargue 와 같은 글). */
  issue_reraised?: { label: string } & Partial<Omit<IssueReargue, "label">>;
};

/** 주의 등급 — 읽는 순서이지 판정이 아니다(registry.attention_of). */
export type Attention = "A" | "B" | "C" | "D";

/**
 * 등록부 한 행(`GET /targets/{key}/registry` — rr_registry 열 이름 그대로 + 풀어 실은 merged). 주장 · 근거 · 영역은 행에 없고 merged
 * 에 있다(전에 claim · cites · subject · domain 을 행 칸으로 적어 두어 행을 누르면 화면이 백지가 됐다). `source=panels` 비교 보기는
 * 저장하지 않은 계산 행이라 저장 칸(verified_by_json …)이 없다.
 */
export type RegistryRow = {
  target_key: string;
  cluster_key: string;
  owner_sub: string;
  visibility: string;
  direction: Direction;
  mechanism: string;
  mechanism_detail: string;
  change_kind: string;
  subject_key: string;
  severity: Severity | (string & {});
  sev3: number;
  judgement: Judgement | (string & {});
  evidence_grade: EvidenceGrade | (string & {});
  precedent: Precedent | (string & {});
  weak_subject: number;
  priority: number;
  support: number;
  contested: number;
  /** 사람 · 코드 상태 — 패널이 전원 기각한 클러스터는 rejected_in_panel 이다. */
  status: RegistryStatus | "rejected_in_panel" | (string & {});
  /** 저장 칸 — 패널만 본 비교 보기(저장하지 않은 계산 행)에는 없다. */
  superseded_by?: string | null;
  updated_at?: number | null;
  verified_by_json?: string | null;
  stale_json?: string | null;
  ra_entity_id?: string | null;
  /** 계산 칸 — 패널만 본 비교 보기에만 있다. */
  rejected?: number;
  human_n?: number;
  family_key?: string;
  support_experts: number | null;
  support_domains: number | null;
  support_units: number | null;
  support_verified: number | null;
  attention: Attention | null;
  issue_id: string | null;
  issue_state: string | null;
  merged: RegistryMerged;
};

/**
 * 등록부 집계가 낸 verdict 후보(registry.verdict_candidate) — 늘 객체다(클러스터가 0건이어도 undetermined 와 까닭 한 줄).
 * 전에 `{reason, conditions[]}` 로 적어 두어 타깃 화면이 `conditions.length` 에서 백지가 됐다 — 서버는 `counts` · `reasons` 를 준다.
 */
export type VerdictCandidate = {
  verdict: Verdict;
  /** 클러스터 수와 판정별 수(열린 · 검증된 행만 센다). */
  counts: { clusters: number; FAIL: number; WARNING: number; OK: number; undetermined: number };
  /** 후보의 까닭 — 줄마다 하나. */
  reasons: string[];
};

export type Registry = {
  target_key: string;
  rows: RegistryRow[];
  /** limit 를 넘겨 잘렸는지(REST 조회는 limit 를 주지 않아 늘 false 다 — MCP 경로가 쓴다). */
  truncated: boolean;
  /** 거른 뒤의 행 수(offset 앞까지 센다). */
  total: number;
  next_offset?: number;
  /** 거른 목록 전체의 지문 — REST 는 한 번에 다 주므로 쪽을 잇지 않는다. */
  ledger_rev: string;
  verdict_candidate: VerdictCandidate;
  verdict_final: Verdict | null;
};

/** 등록부 거름(`GET /targets/{key}/registry` 쿼리) — attention 은 쉼표로 여럿, source=panels 는 패널 finding 만으로 다시 센 비교 보기다. */
export type RegistryQuery = {
  status?: string;
  severity?: string;
  domain?: string;
  attention?: string;
  unit_id?: string;
  source?: "panels";
};

export type VerdictUpdate = { verdict: Verdict; note: string };
/** `PUT /targets/{key}/verdict` 의 답 — 대상 행(routes._target_row). 화면은 등록부를 다시 읽어 확정값을 보인다. */
export type VerdictSaved = {
  target_key: string;
  level: string;
  close_level: string | null;
  verdict_candidate: string | null;
  verdict_final: Verdict | null;
  verdict_note: string | null;
  flow: "panels" | "cells";
};
/** `PUT /registry/{cluster}/status` 의 답(registry.set_status) — verified · dismissed 는 라벨이 함께 선다. */
export type RegistryStatusSet = {
  cluster_key: string;
  status: string;
  updated: number;
  status_source: "human";
  decided_by: string;
  decided_at: number;
  status_log_seq: number;
  label_needed: boolean;
  labels?: JsonObject[];
};
export type RegistryStatusUpdate = {
  status: RegistryStatusInput;
  evidence_ref?: string;
  note?: string;
};

// ── 패널 ─────────────────────────────────────────────────────────────────────

/**
 * 패널 품질(rr_panels.quality_json — runner 의 품질 계산). 패널이 끝나기 전 · 실패한 패널은 빈 객체라 칸마다 없을 수 있다.
 * 전에 `flag` · `tool_calls_n` 으로 적어 두어 끝난 패널이 하나라도 있으면 타깃 화면이 `flag.map` 에서 백지가 됐다.
 */
export type PanelQuality = {
  /** 품질 표지 — low_tool_use · low_ir_cite · adversary_silent · adversary_overreject · spec_parse_failed · over_budget 따위. */
  flags?: string[];
  /** 좌석 중 도구를 쓴 비율(0~1). 재지 못했으면 null. */
  tool_use_rate?: number | null;
  ir_cite_rate?: number | null;
  /** 귀속률(0~1) — null 은 '0 귀속' 이 아니라 '재지 않았다' 다. */
  attribution_rate?: number | null;
  credential?: Credential;
  call_path?: CallPath;
  llm_calls_observed?: number;
};

/** 어떤 LLM 이 점검했는지 — `rr_panels.model_json`(§6.11 D6). 기록이 없으면 빈 객체다. */
export type PanelModel = {
  model?: string;
  /** health_snapshot · caller_reported · unavailable(DDL 주석) — 화면은 글자 그대로 보인다. */
  captured?: string;
};

/** `GET /targets/{key}/panels` 의 패널 한 줄(routes.panels_payload — rr_panels 열 이름 그대로). */
export type Panel = {
  id: string;
  panel_no: number;
  /** Tier 패널은 A · B · C, 쟁점 패널(kind issue)은 그 밖의 값일 수 있다. */
  tier: string | null;
  kind: "coverage" | "issue";
  issue_id: string | null;
  engine: PanelEngine | null;
  tool_mode: ToolMode | null;
  status: PanelStatus;
  conv_id: string | null;
  report_id: number | null;
  seats: JsonValue[];
  modifiers: JsonValue[];
  quality: PanelQuality;
  model: PanelModel;
  llm_calls: number | null;
  retry: number | null;
  error: string | null;
  started_at: number | null;
  ended_at: number | null;
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

export type ResyncQueued = { ra: SyncEntry; adh: SyncEntry };
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
  /** diff 본문의 비교 가능성 그대로(읽지 못하면 빈 객체) — 목록에서 '파서 세대 다름' 을 가른다. */
  comparability: Partial<Comparability>;
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
