import { useCallback, useEffect, useRef, useState } from "react";
import { problemStatus } from "./client";

// Small extension of foundation's fetch layer: no parallel query store or persistent private cache.
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
) {
  const [state, setState] = useState<{
    key: string;
    data?: T;
    error?: unknown;
    loading: boolean;
    updatedAt?: number;
  }>({ key, loading: true });
  const [revision, setRevision] = useState(0);
  const current = useRef(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const generation = ++current.current;
    setState((previous) => ({
      key,
      data: previous.key === key ? previous.data : undefined,
      updatedAt: previous.key === key ? previous.updatedAt : undefined,
      loading: true,
    }));
    void load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted && generation === current.current)
          setState({ key, data, loading: false, updatedAt: Date.now() });
      })
      .catch((error) => {
        if (controller.signal.aborted || generation !== current.current) return;
        setState((previous) => ({
          ...previous,
          data: [401, 403, 404].includes(problemStatus(error) ?? 0)
            ? undefined
            : previous.data,
          error,
          loading: false,
        }));
      });
    return () => controller.abort();
  }, [key, load, revision]);
  // Mark old data as stale after backgrounding, without moving cards under the user's pointer.
  const [stale, setStale] = useState(false);
  useEffect(() => {
    setStale(false);
    const timer = window.setTimeout(() => setStale(true), 60000);
    const onVisible = () => {
      if (document.visibilityState === "visible") setStale(true);
    };
    window.addEventListener("online", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("online", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [state.updatedAt]);
  return {
    ...(state.key === key ? state : { key, loading: true }),
    stale,
    refresh,
  };
}
