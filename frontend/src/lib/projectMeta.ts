// 과제 메타의 순수 판정 — 제품 연결 · 역할 · 홈 칩 거름 · 조직 공개 토글 잠금 · 등록 폼의 제품 행(B34 104 · 105 · 106)
import type {
  Classification,
  Lifecycle,
  McpVisibility,
  ProductRef,
  Project,
  ProjectCard,
  ProjectMember,
  ProjectMeta,
  ProjectRole,
} from "../types";

/** 등급의 말 — 값은 서버 어휘 그대로 보이고 뜻만 덧붙인다. */
export const CLASSIFICATION_LABEL: Record<Classification, string> = {
  internal: "internal — 사내 일반",
  confidential: "confidential — 기밀",
};
export const LIFECYCLE_LABEL: Record<Lifecycle, string> = {
  active: "진행",
  shipped: "출시",
  cancelled: "취소",
  archived: "보관",
};
export const ROLE_LABEL: Record<ProjectRole, string> = { owner: "소유자", editor: "편집자", viewer: "보기" };

/** 과제 행 또는 PATCH 답의 메타 — 9bd5f48 의 과제 행에는 없고 PATCH 답에는 있다. 둘 다 없으면 undefined(모름)다. */
export type KnownMeta = Partial<Pick<ProjectMeta, "classification" | "lifecycle" | "mcp_visibility" | "excluded_reason" | "product_code">> & {
  corpus_excluded?: boolean;
  product_refs?: ProductRef[];
};

/** 서버 열(JSON 글자) 또는 배열에서 제품 연결 행을 푼다. 칸이 아예 없으면 undefined(모름), 비었으면 빈 배열. */
export function parseProductRefs(raw: ProductRef[] | string | null | undefined): ProductRef[] | undefined {
  if (raw === undefined) return undefined;
  if (raw === null || raw === "") return [];
  let value: unknown = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(value)) return [];
  return value
    .filter((r): r is { kind?: unknown; value?: unknown } => typeof r === "object" && r !== null)
    .filter((r) => (r.kind === "ra_model" || r.kind === "product_code") && typeof r.value === "string" && r.value !== "")
    .map((r) => ({ kind: r.kind as ProductRef["kind"], value: r.value as string }));
}

/** 과제 행(+ 방금 받은 PATCH 답)에서 아는 메타를 모은다 — 뒤의 것이 이긴다. 칸이 없으면 그 열쇠가 없다(모름). */
export function knownMeta(project: Partial<Project> | null | undefined, patched?: ProjectMeta | null): KnownMeta {
  const out: KnownMeta = {};
  for (const src of [project ?? {}, patched ?? {}] as Array<Record<string, unknown>>) {
    if ("classification" in src && src.classification !== undefined) out.classification = src.classification as KnownMeta["classification"];
    if ("lifecycle" in src && src.lifecycle !== undefined) out.lifecycle = src.lifecycle as KnownMeta["lifecycle"];
    if ("mcp_visibility" in src && src.mcp_visibility !== undefined) out.mcp_visibility = src.mcp_visibility as KnownMeta["mcp_visibility"];
    if ("excluded_reason" in src && src.excluded_reason !== undefined) out.excluded_reason = src.excluded_reason as KnownMeta["excluded_reason"];
    if ("corpus_excluded" in src && src.corpus_excluded !== undefined && src.corpus_excluded !== null) {
      out.corpus_excluded = Boolean(src.corpus_excluded);
    }
    if ("product_code" in src && src.product_code !== undefined) out.product_code = src.product_code as string | null;
    if ("product_refs_json" in src) {
      const refs = parseProductRefs(src.product_refs_json as ProductRef[] | string | null | undefined);
      if (refs !== undefined) out.product_refs = refs;
    }
  }
  return out;
}

/**
 * '제품 연결 없음' 배지(B34 106 · plan §7.6 — 제품 연결이 없으면 라벨 경로의 제품 일치가 늘 0 이라 자동 확정이 안 된다).
 * 참 = 서버가 '없다' 고 말했다 · 거짓 = 연결이 있다 · null = 서버가 그 칸을 주지 않아 모른다.
 */
export function noProductLink(meta: KnownMeta): boolean | null {
  if (meta.product_refs === undefined && meta.product_code === undefined) return null;
  return (meta.product_refs ?? []).length === 0 && !meta.product_code;
}

/** 이 과제에서의 내 역할 — 멤버 표의 내 줄. 표를 못 받았으면 null(모름). */
export function myRole(members: ProjectMember[] | null | undefined, email: string | null | undefined): ProjectRole | null {
  if (!members || !email) return null;
  const row = members.find((m) => m.email === email);
  return row && (row.role === "owner" || row.role === "editor" || row.role === "viewer") ? (row.role as ProjectRole) : null;
}

/**
 * '조직 공개' 토글(B34 105) — 소유자만 바꾼다(서버는 아니면 403 role_insufficient). 역할을 모르면 잠그지 않되 서버가 거절하면
 * 그 code 로 말한다. 지금 값을 모르면(9bd5f48 은 과제 행에 싣지 않는다) 토글 대신 두 단추를 보인다.
 */
export function visibilityControl(role: ProjectRole | null, current: McpVisibility | null | undefined): {
  locked: boolean;
  lockReason: string | null;
  known: boolean;
} {
  const locked = role !== null && role !== "owner";
  return {
    locked,
    lockReason: locked ? `조직 공개는 과제 소유자만 바꿉니다(지금 ${ROLE_LABEL[role as ProjectRole] ?? role}).` : null,
    known: current === "private" || current === "org",
  };
}

/** 홈 카드 거름(B34 104 · plan §8.2.4 — lifecycle · 내 역할 · 코퍼스 제외 포함, 기본 끔). */
export type HomeFilter = { lifecycle: Lifecycle | ""; role: ProjectRole | ""; includeExcluded: boolean };

/** 카드가 그 칸을 싣는가 — 하나도 안 실으면 그 거름을 잠근다(9bd5f48 은 넷 다 싣지 않는다). */
export function homeFieldsAvailable(cards: ProjectCard[]): { lifecycle: boolean; role: boolean; excluded: boolean; classification: boolean } {
  return {
    lifecycle: cards.some((c) => c.lifecycle !== undefined && c.lifecycle !== null),
    role: cards.some((c) => c.my_role !== undefined && c.my_role !== null),
    excluded: cards.some((c) => c.corpus_excluded !== undefined && c.corpus_excluded !== null),
    classification: cards.some((c) => c.classification !== undefined && c.classification !== null),
  };
}

/** 거름 — 서버가 칸을 주지 않은 거름은 걸지 않는다(모르는 값으로 카드를 숨기지 않는다). */
export function filterCards(cards: ProjectCard[], filter: HomeFilter): ProjectCard[] {
  return cards.filter((c) => {
    if (filter.lifecycle !== "" && c.lifecycle !== undefined && c.lifecycle !== null && c.lifecycle !== filter.lifecycle) return false;
    if (filter.role !== "" && c.my_role !== undefined && c.my_role !== null && c.my_role !== filter.role) return false;
    if (!filter.includeExcluded && c.corpus_excluded) return false;
    return true;
  });
}

/** 등록 폼의 제품 행 — 빈 값은 버린다. 아무것도 없으면 undefined(보내지 않는다). */
export function productRefsBody(rows: ProductRef[]): ProductRef[] | undefined {
  const kept = rows.map((r) => ({ kind: r.kind, value: r.value.trim() })).filter((r) => r.value !== "");
  return kept.length > 0 ? kept : undefined;
}

/** 이메일 꼴(routes.transfer_project 의 검사와 같은 뜻 — '@' 가 가운데 있어야 한다). */
export function emailProblem(email: string): string | null {
  const e = email.trim().toLowerCase();
  if (!e.includes("@") || e.startsWith("@") || e.endsWith("@")) return "heax 사용자 이메일을 적으세요.";
  return null;
}
