// 앱을 열 때 포털 PAT 를 조용히 한 번 등록할지 가르는 판정과 '이 탭에서 해 봤다' 표지 — React 와 떼어 화면 없이 시험한다.
import type { Me, PortalPatAuto } from "../types";

/**
 * 로그인한 사람이고 · 자동 등록이 켜져 있고 · 지금 받아야 할 때만 참이다(백엔드 `portal_pat.auto` 의 `enabled && due`).
 * 익명 · 박스 불일치(이관 직후)는 `portal_pat` 이 null 이라 거짓이다 — 판정은 서버가 하고 화면은 그 두 칸만 읽는다.
 *
 * 자격 암호화 키가 Fernet 키가 아닌 박스(`box.reasons` 의 cred_key_invalid)도 거짓이다 — 등록은 반드시 422 cred_key_absent 로 거절되는데
 * 그 전에 앱이 새 PAT 를 포털 검증에 한 번 보낸다. 키가 없거나(missing_required) 개발용 폴백이면 등록은 되므로 막지 않는다
 * (`box.secrets_valid` 는 그 둘에도 거짓이라 판정에 쓰지 않는다).
 */
export function autoRegisterWanted(me: Me | null | undefined): boolean {
  if (!me || me.anonymous) return false;
  if ((me.box?.reasons ?? []).some((r) => r.code === "cred_key_invalid")) return false;
  const auto = me.portal_pat?.auto;
  return Boolean(auto && auto.enabled && auto.due);
}

/**
 * 같은 탭 세션에서 되풀이하지 않는다는 표지(sessionStorage) — 값은 '해 봤다' 한 글자이고 토큰 · 계정은 담지 않는다.
 * 실패한 시도도 센다. 실패를 다시 시도하는 것은 사람이 설정의 버튼으로 한다.
 */
export const AUTO_TRIED_KEY = "hwax_risk.portal_pat_auto.tried";

type SessionStore = Pick<Storage, "getItem" | "setItem">;

/**
 * 한 번만 여는 문. 저장소를 못 쓰는 창(사생활 모드 · 막힌 저장소 · 접근이 던지는 경우)에서도 이 페이지가 살아 있는 동안은
 * 한 번이다 — 그래서 메모리 표지를 함께 둔다. `storage` 는 부를 때마다 얻는다(접근 자체가 던질 수 있다).
 */
export function createOnceGate(storage: () => SessionStore | null | undefined) {
  let tried = false;
  return {
    tried(): boolean {
      if (tried) return true;
      try {
        return storage()?.getItem(AUTO_TRIED_KEY) === "1";
      } catch {
        return false;
      }
    },
    mark(): void {
      tried = true;
      try {
        storage()?.setItem(AUTO_TRIED_KEY, "1");
      } catch {
        // 저장소가 막혀도 이 페이지 안에서는 한 번이다(메모리 표지).
      }
    },
  };
}

/**
 * 서버가 앱을 열 때의 자동 등록(웹 길)을 쉬는 중이면 그 끝(`auto.paused_until` — 마지막 실패가 웹 등록 거절일 때의 쉼). 게이트웨이 길
 * (Claude 에 넣은 PAT 를 바꿔 받는다)의 실패는 웹 길을 쉬게 하지 않아 null 이다(반대 검토 10-31). 자동 등록이 꺼져 있거나 쉼이
 * 지났으면(화면을 연 채 끝날 수 있다) null 이다. 쉬는 동안 서버의 `due` 는 false 라 앱을 열어도 받지 않는다 — 전에는 서버가 웹 등록
 * 실패를 적지 않아 이 브라우저가 localStorage 에 쉼을 따로 들었다(FE-29, 10-31 risk-flow 에 걷었다).
 */
export function autoPausedUntil(auto: Pick<PortalPatAuto, "enabled" | "paused_until"> | null | undefined, now: number): number | null {
  const until = auto?.paused_until ?? null;
  return auto?.enabled && until !== null && until * 1000 > now ? until : null;
}
