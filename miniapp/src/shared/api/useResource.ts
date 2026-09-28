import { useCallback, useEffect, useRef, useState } from "react";
import { problemStatus } from "./client";

/**
 * Как экран узнаёт об изменениях, сделанных другими людьми, ботом или
 * платформой (F1 §2.3): перечитывание при возврате на вкладку и опрос, пока
 * вкладка видима. `poll` — период опроса в миллисекундах (15 000 — обычный
 * список, 5 000 — ждём внешнего события: подключение чата, одобрение
 * заявки); `false` — без опроса. Скрытая вкладка не опрашивает.
 */
export type ResourceOptions = {
  poll?: number | false;
  /** Перечитать при возврате на вкладку и в сеть. По умолчанию — да. */
  revalidate?: boolean;
};

export const POLL_LIST_MS = 15000;
export const POLL_WAITING_MS = 5000;
/** Возврат на вкладку не перечитывает чаще — фокус и видимость приходят парой. */
const REVALIDATE_GAP_MS = 2000;

/** Время последнего обновления любого экрана — для тихой подписи «Обновлено …». */
export const RESOURCE_UPDATED_EVENT = "ds-resource-updated";

// One fetch layer for both surfaces. reload resolves only after the authoritative GET.
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  options: ResourceOptions = {},
) {
  const { poll = false, revalidate = true } = options;
  const [state, setState] = useState<{
    key: string;
    data?: T;
    error?: unknown;
    loading: boolean;
    refreshing: boolean;
    updatedAt?: number;
  }>({ key, loading: true, refreshing: false });
  const active = useRef<AbortController | null>(null);
  const latest = useRef({ key, load });
  latest.current = { key, load };
  const last = useRef(0);
  const reload = useCallback(async () => {
    const { key, load } = latest.current;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    last.current = Date.now();
    // Повторное чтение того же ключа — тихое: данные на экране остаются,
    // скелетон и «Загружаем…» — только при первой загрузке.
    setState((previous) => {
      const same = previous.key === key && previous.data !== undefined;
      return {
        key,
        loading: !same,
        refreshing: same,
        data: previous.key === key ? previous.data : undefined,
        error: same ? previous.error : undefined,
        updatedAt: previous.key === key ? previous.updatedAt : undefined,
      };
    });
    try {
      const data = await load(controller.signal);
      if (controller.signal.aborted)
        throw new DOMException("Aborted", "AbortError");
      const updatedAt = Date.now();
      setState({ key, data, loading: false, refreshing: false, updatedAt });
      window.dispatchEvent(new CustomEvent(RESOURCE_UPDATED_EVENT, { detail: updatedAt }));
      return data;
    } catch (error) {
      if (!controller.signal.aborted)
        setState((previous) => ({
          ...previous,
          loading: false,
          refreshing: false,
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
  // Возврат на вкладку и в сеть — тихое перечитывание.
  useEffect(() => {
    if (!revalidate) return;
    const onReturn = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - last.current < REVALIDATE_GAP_MS) return;
      refresh();
    };
    window.addEventListener("focus", onReturn);
    window.addEventListener("online", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      window.removeEventListener("online", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [revalidate, refresh]);
  // Опрос, пока вкладка видима; скрытая вкладка сеть не тратит.
  useEffect(() => {
    if (!poll) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && Date.now() - last.current >= poll - 250) refresh();
    }, poll);
    return () => window.clearInterval(timer);
  }, [poll, refresh, key]);
  return {
    ...(state.key === key ? state : { key, loading: true, refreshing: false }),
    /**
     * Прежняя отметка «данные могли измениться»: экран сам перечитывается при
     * возврате и по опросу (F1 §2.3), поэтому отметка больше не ставится.
     */
    stale: false,
    refresh,
    reload,
  };
}
