// 포털 PAT 을 브라우저에서 바로 발급받는 얇은 래퍼 — 앱 SPA 와 포털이 같은 오리진이라 세션·CSRF 를 그대로 쓴다
//
// 왜 이 파일이 있나. 앱 서버는 사용자를 대신해 포털 `POST /auth/pat` 을 부를 수 없다 —
// 포털 `require_csrf`(deps.py)는 double-submit 이라 **브라우저의 `hwax_csrf` 쿠키**를 요구하고
// Bearer 를 면제하지 않는다. 그래서 앱 서버가 사용자 heax 토큰을 들고 있어도 발급이 안 된다.
// 반면 앱 SPA 는 포털과 같은 오리진에서 돌아(앱은 `/apps/hwax_risk/`, 포털 API 는 `/auth/…`)
// 쿠키와 CSRF 헤더를 그대로 실을 수 있다. 그래서 발급은 **브라우저가** 하고, 받은 값을 곧바로
// 앱 `PUT /me/portal-pat` 에 넘긴다 — 사람이 값을 손으로 옮기는 단계가 사라진다.
//
// 포털 코드는 한 줄도 바꾸지 않는다. scopes 관문(`risk_pat_require_read_only`)도 건드리지 않는다 —
// 여기서 `scopes:['read']` 로 발급하므로 그 검사를 그대로 통과한다.

/** 포털 `POST /auth/pat` 응답(pat.py PatCreated). `token` 은 발급 시 한 번만 온다. */
export type PortalPatMinted = {
  token: string;
  jti: string;
  name: string;
  audiences: string[];
  scopes: string[];
  exp: number;
};

/** 앱이 요구하는 발급 조건 — `aud ∋ mcp-gateway` · `scopes == ['read']`(§8.2.3·§8.2.7). */
export const MINT_BODY = {
  name: "hwax-risk",
  audiences: ["mcp-gateway"],
  scopes: ["read"],
  ttl_days: 90,
} as const;

/** 포털이 double-submit 으로 요구하는 CSRF 쿠키(포털 `auth/cookies.py` CSRF_COOKIE). JS 가 읽을 수 있다. */
const CSRF_COOKIE = "hwax_csrf";

function csrfToken(): string | null {
  // 쿠키 이름은 정확히 일치해야 한다 — `hwax_csrf_other` 같은 접두 일치를 잡지 않는다.
  for (const part of document.cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === CSRF_COOKIE) return decodeURIComponent(part.slice(eq + 1));
  }
  return null;
}

/** 발급이 왜 안 됐는지 사람이 읽을 수 있게 — 코드로 분기하지 않고 문구로 만든다. */
export class PortalMintError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * 포털에서 PAT 한 장을 발급받는다. 값은 돌려주기만 하고 어디에도 저장·기록하지 않는다.
 *
 * 실패는 사유를 구분해 올린다 — 이 버튼이 안 되는 이유는 대개 셋이고 각각 다음 할 일이 다르다.
 * (1) 포털 세션이 아님(쿠키 없음) (2) `feat:api-token` 권한 없음(403, 관리자가 부여) (3) 그 밖.
 */
export async function mintPortalPat(): Promise<PortalPatMinted> {
  const csrf = csrfToken();
  if (!csrf) {
    throw new PortalMintError(
      0,
      "포털 세션을 찾지 못했습니다. 이 화면을 포털 창(같은 브라우저·같은 오리진)에서 열어야 발급할 수 있습니다.",
    );
  }
  // 절대 경로다 — 앱 API 는 상대 경로(`api/`)를 쓰지만 이 호출만 포털 쪽이다.
  const res = await fetch("/auth/pat", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(MINT_BODY),
  });
  if (!res.ok) {
    if (res.status === 403) {
      throw new PortalMintError(
        403,
        "포털이 토큰 발급 권한(feat:api-token)을 요구합니다. 관리자에게 그 권한을 요청한 뒤 다시 누르세요.",
      );
    }
    if (res.status === 401) {
      throw new PortalMintError(401, "포털 로그인이 만료됐습니다. 포털에서 다시 로그인한 뒤 누르세요.");
    }
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
    throw new PortalMintError(res.status, `포털 토큰 발급이 거부됐습니다 — ${detail}`);
  }
  return (await res.json()) as PortalPatMinted;
}
