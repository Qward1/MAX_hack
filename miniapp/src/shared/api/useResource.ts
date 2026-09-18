import { useCallback, useEffect, useRef, useState } from "react";
import { problemStatus } from "./client";

// One fetch layer for both surfaces. reload resolves only after the authoritative GET.
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
  const active = useRef<AbortController | null>(null);
  const latest = useRef({ key, load });
  latest.current = { key, load };
  const reload = useCallback(async () => {
    const { key, load } = latest.current;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState((previous) => ({
      key,
      loading: true,
      data: previous.key === key ? previous.data : undefined,
      updatedAt: previous.key === key ? previous.updatedAt : undefined,
    }));
    try {
      const data = await load(controller.signal);
      if (controller.signal.aborted)
        throw new DOMException("Aborted", "AbortError");
      setState({ key, data, loading: false, updatedAt: Date.now() });
      return data;
    } catch (error) {
      if (!controller.signal.aborted)
        setState((previous) => ({
          ...previous,
          loading: false,
          error,
          data: [401, 403, 404].includes(problemStatus(error) ?? 0)
            ? undefined
            : previous.data,
        }));
      throw error;
    }
  }, []);
  const refresh = useCallback(() => {
    void reload().catch(() => {});
  }, [reload]);
  useEffect(() => {
    refresh();
    return () => active.current?.abort();
  }, [key, load, refresh]);
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
    reload,
  };
}
