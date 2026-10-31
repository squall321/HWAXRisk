// 앱을 열 때 포털 PAT 를 조용히 한 번 등록할지 가르는 판정과 '이 탭에서 해 봤다' 표지 — React 와 떼어 화면 없이 시험한다.
import type { Me } from "../types";

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
 * 자동 등록이 등록 단계에서 실패한 뒤 이 브라우저가 쉬는 표지(localStorage) — 탭 세션마다 한 번(위의 문)으로는 새 탭마다 새 PAT 를 받아
 * 등록에 보냈다. 값은 {until, code} 하나이고 토큰 · 계정은 담지 않는다. 사람이 누른 버튼 · 스위치는 쉼을 보지 않고, 성공하면 걷는다.
 */
export const AUTO_HELD_KEY = "hwax_risk.portal_pat_auto.held";
/** 일시 실패(네트워크 · 5xx · portal_unreachable)의 쉼 — 백엔드 routes.AUTO_RETRY_TRANSIENT_S(600초)와 같다. */
export const AUTO_HOLD_TRANSIENT_MS = 600_000;
/** 사람이 고쳐야 하는 실패의 쉼 — 백엔드 HWAXRISK_PAT_AUTO_RETRY_S 의 기본값(6시간)과 같다. */
export const AUTO_HOLD_FINAL_MS = 6 * 3600_000;

export type AutoHold = { until: number; code: string };

type LocalStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** 쉼 표지 — 저장소를 못 쓰는 창에서도 이 페이지 안에서는 쉰다(메모리 표지). 읽을 수 없는 값은 없는 것으로 본다. */
export function createAutoHold(storage: () => LocalStore | null | undefined) {
  let memory: AutoHold | null = null;
  function stored(): AutoHold | null {
    try {
      const raw = storage()?.getItem(AUTO_HELD_KEY);
      if (!raw) return null;
      const value = JSON.parse(raw) as Partial<AutoHold>;
      return typeof value.until === "number" && typeof value.code === "string" ? { until: value.until, code: value.code } : null;
    } catch {
      return null;
    }
  }
  return {
    /** 지금 쉬는 중이면 그 표지, 아니면 null(지난 쉼은 없는 것이다). */
    current(now: number): AutoHold | null {
      const found = stored() ?? memory;
      return found && found.until > now ? found : null;
    },
    hold(value: AutoHold): void {
      memory = value;
      try {
        storage()?.setItem(AUTO_HELD_KEY, JSON.stringify(value));
      } catch {
        // 저장소가 막혀도 이 페이지 안에서는 쉰다(메모리 표지).
      }
    },
    clear(): void {
      memory = null;
      try {
        storage()?.removeItem(AUTO_HELD_KEY);
      } catch {
        // 저장소가 막혔으면 지울 것도 없다.
      }
    },
  };
}
