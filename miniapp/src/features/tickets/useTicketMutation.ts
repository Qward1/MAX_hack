import { useEffect, useRef, useState } from "react";
import { problemStatus, retryable } from "../../shared/api/client";

/** Что случилось и что делать — без кодов, «ошибок» и вины человека. */
export function safeError(error: unknown, saving = false, resident = false) {
  const messages: Record<number, string> = resident
    ? {
        401: "Сессия MAX истекла. Закройте мини-приложение и откройте его снова.",
        403: "Это действие вам сейчас недоступно.",
        404: "Не нашли эту заявку. Возможно, её уже закрыли. Обновите страницу.",
        409: "Данные уже изменились. Обновите страницу и повторите.",
        422: "Ответ не принят. Обновите страницу и повторите.",
        429: "Слишком много попыток. Подождите минуту и повторите.",
      }
    : {
        401: "Сессия истекла. Войдите снова.",
        403: "Действие недоступно в вашей роли. Уточните права у администратора УК.",
        404: "Заявка не найдена или больше недоступна.",
        409: "Заявка уже изменилась. Обновите данные.",
        422: "Проверьте поля формы.",
        429: "Слишком много запросов. Подождите минуту и повторите.",
      };
  return (
    messages[problemStatus(error) ?? 0] ??
    (saving
      ? "Не удалось сохранить. Проверьте интернет и повторите."
      : "Не удалось загрузить данные. Проверьте интернет и повторите.")
  );
}
type Operation<T, D> = {
  write: (key: string) => Promise<T>;
  read: () => Promise<D>;
  success: (result: T, data: D) => string;
  conflict?: (error: unknown, data: D) => string | undefined;
};
export function useTicketMutation<T, D>() {
  const pending = useRef<{
    operation: Operation<T, D>;
    key: string;
    result?: T;
    written: boolean;
  } | null>(null);
  const lock = useRef(false);
  const alive = useRef(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const [canRetry, setCanRetry] = useState(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function execute() {
    if (lock.current || !pending.current) return;
    lock.current = true;
    setSaving(true);
    setError(undefined);
    setMessage("");
    setCanRetry(false);
    const attempt = pending.current;
    try {
      if (!attempt.written) {
        attempt.result = await attempt.operation.write(attempt.key);
        attempt.written = true;
      }
      const data = await attempt.operation.read();
      if (!alive.current) return;
      setMessage(attempt.operation.success(attempt.result!, data));
      pending.current = null;
    } catch (failure) {
      if (!alive.current) return;
      const status = problemStatus(failure);
      if ([401, 403, 404, 409].includes(status ?? 0)) {
        try {
          const data = await attempt.operation.read();
          if (alive.current)
            setMessage(
              attempt.operation.conflict?.(failure, data) ??
                (status === 409
                  ? "Заявка уже изменилась. Мы обновили данные."
                  : safeError(failure, true)),
            );
        } catch {
          if (alive.current) setError(failure);
        }
        pending.current = null;
      } else {
        setError(failure);
        setCanRetry(retryable(failure));
        if (!retryable(failure)) pending.current = null;
      }
    } finally {
      lock.current = false;
      if (alive.current) setSaving(false);
    }
  }
  return {
    saving,
    error,
    message,
    canRetry,
    uncertain: pending.current !== null,
    clearFeedback: () => {
      if (lock.current || pending.current) return;
      setError(undefined);
      setMessage("");
      setCanRetry(false);
    },
    run: (operation: Operation<T, D>) => {
      if (lock.current || pending.current) return;
      pending.current = { operation, key: crypto.randomUUID(), written: false };
      void execute();
    },
    retry: () => {
      void execute();
    },
  };
}
