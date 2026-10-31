// 앱을 열 때 포털 PAT 자동 등록 — 로그인한 사람의 auto.enabled && due 면 조용히 한 번 발급해 등록하고 실패만 한 줄로 알린다.
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { describeError, riskApi } from "../api/risk.api";
import { registerFromPortal } from "../api/portalPat";
import { autoRegisterWanted, createOnceGate } from "../api/autoPortalPat";
import { describePatFailure } from "../api/patErrors";
import type { PatFailureText } from "../api/patErrors";
import { Banner, Button } from "../ui/primitives";

type AutoPortalPatState = {
  /** 자동 등록이 끝날 때마다(성공 · 실패) 오른다 — 설정 화면이 이 값으로 `GET /me` 를 다시 읽는다. */
  version: number;
  /** 지금 자동 등록 중이다 — 설정 화면이 손 버튼을 잠근다(두 번 발급하지 않게). */
  running: boolean;
  failure: PatFailureText | null;
  dismiss: () => void;
};

const AutoPortalPatContext = createContext<AutoPortalPatState>({
  version: 0,
  running: false,
  failure: null,
  dismiss: () => undefined,
});

// 탭 세션마다 한 번 — sessionStorage 를 못 쓰는 창에서도 이 페이지 안에서는 한 번이다(createOnceGate 주석). 등록에서 실패한 뒤의
// 쉼은 서버가 든다 — 웹 등록 실패도 적고 쉬는 동안 `due` 가 false 다(10-31 risk-flow — 전에는 localStorage 에 쉼을 따로 들었다).
const gate = createOnceGate(() => window.sessionStorage);

function describeAutoFailure(err: unknown): PatFailureText {
  const known = describePatFailure(err);
  if (known) return known;
  const { title, detail } = describeError(err);
  return { title, detail };
}

/**
 * 앱 셸을 감싼다. 첫 마운트에 `GET /me` 를 읽어 `auto.enabled && auto.due` 면 설정의 버튼과 같은 일
 * (`/auth/pat` 발급 → `PUT /me/portal-pat`, 출처 web)을 한 번 한다. 막지 않는다 — 성공은 말하지 않고 실패만 한 줄로 알린다.
 *
 * StrictMode 의 두 번 마운트는 첫 번째의 `GET /me` 를 끊으므로(abort) 발급은 한 번만 나간다. 문(gate)은 발급을 시작할 때 닫는다.
 */
export function AutoPortalPatProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const [running, setRunning] = useState(false);
  const [failure, setFailure] = useState<PatFailureText | null>(null);

  useEffect(() => {
    if (gate.tried()) return;
    const controller = new AbortController();
    (async () => {
      let wanted = false;
      try {
        wanted = autoRegisterWanted(await riskApi.getMe({ signal: controller.signal }));
      } catch {
        // 신원을 못 읽은 것은 화면마다 제 배너가 말한다 — 여기서 겹쳐 말하지 않는다.
        return;
      }
      if (controller.signal.aborted || !wanted || gate.tried()) return;
      gate.mark();
      setRunning(true);
      try {
        await registerFromPortal();
      } catch (err) {
        setFailure(describeAutoFailure(err));
      } finally {
        setRunning(false);
        setVersion((v) => v + 1);
      }
    })();
    return () => controller.abort();
  }, []);

  return (
    <AutoPortalPatContext.Provider value={{ version, running, failure, dismiss: () => setFailure(null) }}>
      {children}
    </AutoPortalPatContext.Provider>
  );
}

export function useAutoPortalPat(): AutoPortalPatState {
  return useContext(AutoPortalPatContext);
}

/** 자동 등록 실패 한 줄 — 막지 않고 알리기만 한다. 다시 하는 길은 설정의 버튼이다. */
export function AutoPortalPatNotice() {
  const { failure, dismiss } = useAutoPortalPat();
  if (!failure) return null;
  return (
    <Banner tone="warn" live="status" title="포털 PAT 자동 등록을 못 했습니다." detail={`${failure.title} ${failure.detail}`}>
      <span className="flex items-center gap-2">
        <Link to="/settings" className="text-sm underline underline-offset-4">
          설정에서 다시 하기
        </Link>
        <Button type="button" variant="ghost" size="sm" onClick={dismiss}>
          닫기
        </Button>
      </span>
    </Banner>
  );
}
