import { useEffect } from "react";
import { problemStatus, retryable } from "../shared/api/client";
import type { SignalSummary } from "../shared/api/signals";
import { adminUrl } from "./AdminApp";

/** Опрос очереди — раз в 15 секунд и только пока вкладка видима. */
export const POLL_MS = 15000;

export function signalsUrl(values: Record<string, string | undefined> = {}) {
  return adminUrl({ section: "signals", ...values });
}

export function signalError(error: unknown): string {
  const messages: Record<number, string> = {
    401: "Сессия истекла. Войдите снова.",
    403: "Действие недоступно в вашей роли.",
    404: "Сигнал не найден или больше недоступен.",
    409: "Сигнал уже изменился. Данные обновлены.",
    422: "Проверьте поля формы.",
    429: "Слишком много запросов. Попробуйте ещё раз.",
  };
  return messages[problemStatus(error) ?? 0] ?? "Не удалось загрузить данные.";
}

export function SignalState({
  loading = false,
  error,
  retry,
}: {
  loading?: boolean;
  error?: unknown;
  retry?: () => void;
}) {
  return (
    <section className="state-panel" aria-busy={loading}>
      <p role={loading ? "status" : "alert"}>
        {loading ? "Загружаем актуальные данные…" : signalError(error)}
      </p>
      {!loading && retry && retryable(error) && (
        <button className="ticket-button secondary" onClick={retry}>
          Повторить загрузку
        </button>
      )}
    </section>
  );
}

/** Обновление по таймеру, пока вкладка видима, и сразу при возврате на неё. */
export function usePolling(refresh: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, enabled]);
}

export function strengthTone(strength: string): string {
  return strength === "critical"
    ? "tone-attention"
    : strength === "weak"
      ? "tone-neutral"
      : "tone-active";
}

export function placeLine(item: SignalSummary): string {
  return [
    item.place.entrance && `Подъезд ${item.place.entrance.value}`,
    item.place.floor && `Этаж ${item.place.floor.value}`,
    item.place.since && `С ${item.place.since.value}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
