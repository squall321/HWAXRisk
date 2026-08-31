// 화면 공통 비동기 상태 훅 — 로딩·오류·재조회와 5초 폴링을 한곳에서 만든다(계획 §8.2.4 폴링 규약).
import { useCallback, useEffect, useRef, useState } from "react";
import type { DependencyList } from "react";
import { isAborted } from "../api/risk.api";

/** §8.2.4 가 정한 폴링 주기. 화면을 떠나면 훅이 스스로 멈춘다. */
export const POLL_MS = 5000;

export type Async<T> = {
  data: T | null;
  loading: boolean;
  error: unknown;
  /** 같은 인자로 다시 부른다. 이전 데이터는 남겨 두어 폴링 중 화면이 깜빡이지 않는다. */
  reload: () => void;
};

/**
 * `load` 를 deps 가 바뀔 때마다 부르고 취소 신호를 넘긴다.
 * 중단(AbortError)은 오류로 세지 않는다 — 화면을 떠난 뒤 배너가 뜨지 않게 한다.
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
  enabled = true,
): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let alive = true;
    setLoading(true);
    loadRef.current(controller.signal).then(
      (value) => {
        if (!alive) return;
        setData(value);
        setError(null);
        setLoading(false);
      },
      (err) => {
        if (!alive || isAborted(err)) return;
        setError(err);
        setLoading(false);
      },
    );
    return () => {
      alive = false;
      controller.abort();
    };
    // deps 는 호출부가 정한다.
  }, [...deps, enabled, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload };
}

/** `ms` 가 null 이면 멈춘다(진행 중인 잡이 없을 때 폴링을 끄는 용도). */
export function useInterval(callback: () => void, ms: number | null) {
  const saved = useRef(callback);
  saved.current = callback;
  useEffect(() => {
    if (ms === null) return;
    const id = window.setInterval(() => saved.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}
