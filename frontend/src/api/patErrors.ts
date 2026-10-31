// 포털 PAT 발급 · 등록 실패를 사람이 읽는 문구로 — 설정 화면과 앱을 열 때의 자동 등록 알림이 같은 표를 쓴다(code 로 가른다).
import { isApiError } from "./risk.api";
import { PortalMintError } from "./portalPat";

export type PatFailureText = { title: string; detail: string };

/** `PUT /me/portal-pat` 의 거절(§8.2.3) — 서버 code 를 사람이 읽는 문구와 다음 할 일로 바꾼다. */
export const PAT_ERRORS: Record<string, PatFailureText> = {
  pat_invalid: {
    title: "포털이 이 PAT 를 받지 않았습니다.",
    detail: "형식이 포털 PAT(JWT 3분절)가 아니거나 포털 검증 호출이 거부했습니다. 값을 다시 복사하거나 포털에서 새로 발급하세요.",
  },
  pat_email_mismatch: {
    title: "내 계정의 PAT 가 아닙니다.",
    detail: "PAT 안의 email 이 지금 로그인한 계정과 다릅니다. 내 계정으로 로그인한 상태에서 발급한 PAT 를 넣으세요.",
  },
  pat_audience: {
    title: "발급 조건이 맞지 않습니다.",
    detail: "aud 에 mcp-gateway 가 없거나 scope 가 api 가 아닙니다. 발급 화면에서 두 값을 맞춰 다시 발급하세요.",
  },
  pat_expiring: {
    title: "곧 만료되는 PAT 입니다.",
    detail: "만료까지 24시간이 채 남지 않았습니다. ttl 을 365일 이하 범위에서 넉넉히 잡아 다시 발급하세요.",
  },
  // 포털 발급 화면이 scopes 를 ['read','write'] 로 주므로 링크를 그대로 따라간 사용자가 만나는 코드다.
  pat_scope_too_broad: {
    title: "범위가 넓은 PAT 입니다.",
    detail:
      "이 앱은 scopes 가 ['read'] 인 PAT 만 등록합니다. 위의 '포털에서 발급해 등록' 을 쓰면 그 범위로 바로 만들어 줍니다.",
  },
  cred_key_absent: {
    title: "이 박스에 자격 암호키가 없습니다.",
    detail:
      "PAT 를 평문으로 저장하지 않으므로 키가 없으면 등록하지 않습니다. 운영자가 데이터 디렉터리의 cred.key 를 만들어야 합니다.",
  },
  // 설정 문제를 토큰 문제로 읽지 않게 따로 적는다(502).
  portal_unreachable: {
    title: "포털에 닿지 못했습니다 — PAT 문제가 아닙니다.",
    detail:
      "앱이 포털을 부르는 주소(HWAXRISK_PORTAL_BASE)가 실제 포털 오리진을 가리키지 않습니다. 토큰을 다시 발급해도 같은 오류가 납니다 — 운영자가 그 설정을 고쳐야 합니다.",
  },
};

/**
 * 발급 단계의 실패(포털 세션 없음 · `feat:api-token` 없음 · 로그인 만료 — 문구가 곧 사유다)와 등록 단계의 아는 거절은 전용
 * 문구로, 그 밖은 null 이다 — 호출자가 공용 배너(describeError)로 접는다.
 */
export function describePatFailure(err: unknown): PatFailureText | null {
  if (err instanceof PortalMintError) return { title: "포털에서 PAT 를 발급하지 못했습니다.", detail: err.message };
  if (isApiError(err)) return PAT_ERRORS[err.code] ?? null;
  return null;
}
