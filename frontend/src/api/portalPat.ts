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
import { NetworkError, isApiError, riskApi } from "./risk.api";
import type { AutoHold } from "./autoPortalPat";
import { AUTO_HOLD_FINAL_MS, AUTO_HOLD_TRANSIENT_MS } from "./autoPortalPat";

/** 포털 `POST /auth/pat` 응답(pat.py PatCreated). `token` 은 발급 시 한 번만 온다. */
export type PortalPatMinted = {
  token: string;
  jti: string;
  name: string;
  audiences: string[];
  scopes: string[];
  exp: number;
};

/**
 * 앱이 요구하는 발급 조건 — `aud ∋ mcp-gateway` · `scopes == ['read']`(§8.2.3·§8.2.7). 청중 `step-forge` 는 위임 캡처의
 * REST 다리(게이트웨이 `/api/step-forge`)가 요구한다 — 없으면 앱이 `due_reason: "audience"` 로 다시 받기를 바란다(백엔드
 * routes.PORTAL_PAT_WANTED 와 같은 값이다). 이름 `hwax-risk` 는 백엔드가 갈아 끼울 때 옛 PAT 를 폐기하는 표지라 바꾸지 않는다.
 */
export const MINT_BODY = {
  name: "hwax-risk",
  audiences: ["mcp-gateway", "step-forge"],
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

/** 방금 받은 PAT 를 등록하지 못한 뒤 그 PAT 를 어떻게 했나 — 포털에서 폐기함 · 폐기하지 못함 · 등록됐는지 몰라 건드리지 않음. */
export type MintedFate = "revoked" | "revoke_failed" | "unknown";

/**
 * 발급은 됐는데 앱 등록이 실패했다 — 원래 거절(`rejection`)과 방금 받은 PAT 의 처리(`minted`)를 함께 싣는다. 받은 PAT 는 90일짜리
 * 자격이고 쥔 곳이 없으므로 그대로 두지 않는다(registerFromPortal).
 */
export class PortalRegisterError extends Error {
  readonly rejection: unknown;
  readonly jti: string;
  readonly minted: MintedFate;
  constructor(rejection: unknown, jti: string, minted: MintedFate) {
    super(rejection instanceof Error ? rejection.message : String(rejection));
    this.name = "PortalRegisterError";
    this.rejection = rejection;
    this.jti = jti;
    this.minted = minted;
  }
}

/**
 * 등록 거절이 저장 전에 났나 — 앱이 답한 4xx(검사 · 포털 검증 거부 · 암호키)와 502 portal_unreachable(포털 검증에 못 닿음)은 저장 전이다
 * (routes._register_portal_pat 은 검사를 다 지난 뒤에 저장한다). 그 밖(다른 5xx · 네트워크 · 읽을 수 없는 답)은 저장됐을 수도 있다.
 */
export function refusedBeforeStore(err: unknown): boolean {
  return isApiError(err) && ((err.status >= 400 && err.status < 500) || err.code === "portal_unreachable");
}

/**
 * 방금 받은 PAT 를 그 토큰 자신으로 폐기한다 — 포털 `POST /auth/pat/revoke-self`(Bearer 그 PAT · 청중 mcp-gateway, 쿠키 · CSRF 를 쓰지
 * 않는다 — 백엔드가 갈아 끼운 PAT 를 폐기하는 길과 같다). 최선 노력이라 던지지 않는다.
 */
async function revokeMinted(token: string): Promise<boolean> {
  try {
    const res = await fetch("/auth/pat/revoke-self", {
      method: "POST",
      credentials: "omit",
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * 포털에서 발급해 곧바로 앱에 등록한다(출처 `web`) — 설정의 「포털에서 발급해 등록」 · 앱을 열 때의 자동 등록 · 자동 스위치를
 * 켤 때가 모두 이 길을 지난다. 출처를 `web` 으로 적어야 다음 갱신 때 백엔드가 이 PAT 를 폐기한다(`manual` 로 적히면 쌓인다).
 * 토큰은 이 함수 안에서만 산다 — 화면 상태 · 저장소 · 로그에 남기지 않고 jti 만 돌려준다.
 *
 * 등록이 실패하면 방금 받은 PAT 를 버려 두지 않는다 — 전에는 앱이 등록을 거절하는 박스(포털 주소 오지정 · 계정 불일치 따위)에서 새 탭마다
 * 쥔 곳 없는 90일 PAT 가 하나씩 포털에 쌓였다. 저장 전 거절이면 곧바로 폐기하고, 저장됐을 수도 있는 실패면 `GET /me` 로 그 jti 가
 * 등록됐는지 보고(됐으면 성공) 아니면 폐기한다. 등록 여부를 못 읽으면 건드리지 않는다(등록된 자격을 폐기하지 않게). 실패는
 * `PortalRegisterError` 로 올린다.
 */
export async function registerFromPortal(): Promise<{ jti: string }> {
  const minted = await mintPortalPat();
  try {
    await riskApi.putPortalPat(minted.token, "web");
    return { jti: minted.jti };
  } catch (err) {
    if (!refusedBeforeStore(err)) {
      let stored: boolean | null = null;
      try {
        const pat = (await riskApi.getMe()).portal_pat;
        // portal_pat 이 null 이면(익명 · 박스 불일치) 등록 여부를 모른다.
        stored = pat ? pat.jti === minted.jti : null;
      } catch {
        stored = null;
      }
      if (stored === true) return { jti: minted.jti };
      if (stored === null) throw new PortalRegisterError(err, minted.jti, "unknown");
    }
    throw new PortalRegisterError(err, minted.jti, (await revokeMinted(minted.token)) ? "revoked" : "revoke_failed");
  }
}

/**
 * 자동 등록이 등록에서 실패했을 때 이 브라우저가 쉬는 동안 — 일시 실패(네트워크 · 5xx · portal_unreachable)는 짧게, 사람이 고쳐야 하는
 * 실패는 길게(백엔드가 게이트웨이 교환 실패에 거는 쉼과 같은 두 값). 발급 단계의 실패는 PAT 를 만들지 않아 쉬지 않는다(null).
 */
export function autoHoldOf(err: unknown, now: number): AutoHold | null {
  if (!(err instanceof PortalRegisterError)) return null;
  const rejection = err.rejection;
  const code = isApiError(rejection) ? rejection.code : rejection instanceof NetworkError ? "network" : "unknown";
  const transient = rejection instanceof NetworkError || (isApiError(rejection) && rejection.status >= 500);
  return { until: now + (transient ? AUTO_HOLD_TRANSIENT_MS : AUTO_HOLD_FINAL_MS), code };
}
