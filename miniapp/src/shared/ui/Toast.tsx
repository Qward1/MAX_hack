import { useEffect, useState } from "react";

/**
 * Общие уведомления о результате (F-14): «Сохранено», «Отправлено в очередь».
 * Одно место на все поверхности: экран вызывает `notify`, оболочка держит
 * `<Toaster />`. Сообщение объявляется диктору (`role="status"`), фокус не
 * перехватывает и само исчезает через несколько секунд.
 */
export const TOAST_EVENT = "ds-toast";
const TOAST_MS = 4500;

export type ToastTone = "success" | "info" | "danger";

export function notify(text: string, tone: ToastTone = "success"): void {
  window.dispatchEvent(new CustomEvent(TOAST_EVENT, { detail: { text, tone } }));
}

type Item = { id: number; text: string; tone: ToastTone };

export function Toaster() {
  const [items, setItems] = useState<Item[]>([]);
  useEffect(() => {
    let counter = 0;
    const timers = new Set<number>();
    const add = (event: Event) => {
      const { text, tone } = (event as CustomEvent<{ text: string; tone: ToastTone }>).detail;
      const id = ++counter;
      setItems((current) => [...current.slice(-2), { id, text, tone }]);
      const timer = window.setTimeout(() => {
        setItems((current) => current.filter((item) => item.id !== id));
        timers.delete(timer);
      }, TOAST_MS);
      timers.add(timer);
    };
    window.addEventListener(TOAST_EVENT, add);
    return () => {
      window.removeEventListener(TOAST_EVENT, add);
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);
  return (
    <div className="ds-toaster" role="status" aria-live="polite">
      {items.map((item) => (
        <p key={item.id} className={`ds-toast ds-tone-${item.tone}`}>
          <span aria-hidden="true">{item.tone === "success" ? "✓" : item.tone === "danger" ? "!" : "●"}</span>
          {item.text}
        </p>
      ))}
    </div>
  );
}
