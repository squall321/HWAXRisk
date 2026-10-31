// 앱을 열 때 포털 PAT 를 조용히 한 번 등록할지 가르는 판정과 '이 탭에서 해 봤다' 표지 — React 와 떼어 화면 없이 시험한다.
import type { Me } from "../types";

/**
 * 로그인한 사람이고 · 자동 등록이 켜져 있고 · 지금 받아야 할 때만 참이다(백엔드 `portal_pat.auto` 의 `enabled && due`).
 * 익명 · 박스 불일치(이관 직후)는 `portal_pat` 이 null 이라 거짓이다 — 판정은 서버가 하고 화면은 그 두 칸만 읽는다.
 */
export function autoRegisterWanted(me: Me | null | undefined): boolean {
  if (!me || me.anonymous) return false;
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
