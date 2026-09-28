import { useSyncExternalStore } from "react";

/**
 * Светлая или тёмная тема — выбор на этом устройстве.
 *
 * Без выбора тема следует за MAX и системой (`prefers-color-scheme` в
 * tokens.css). Выбор — атрибут `data-theme` на <html> и запись `ds:theme` в
 * хранилище браузера; до первой отрисовки его ставит `public/theme-init.js`.
 * Хранилище в MAX может быть недоступно — тогда выбор действует до перезагрузки.
 */
export type Theme = "light" | "dark";

const KEY = "ds:theme";
const DARK = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function media(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(DARK) : null;
}

/** Выбранная на устройстве тема или null — следовать за MAX и системой. */
export function chosenTheme(): Theme | null {
  const value = document.documentElement.dataset.theme;
  return value === "light" || value === "dark" ? value : stored();
}

/** Тема, которая сейчас на экране. */
export function currentTheme(): Theme {
  return chosenTheme() ?? (media()?.matches ? "dark" : "light");
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* хранилище недоступно — выбор действует до перезагрузки */
  }
  listeners.forEach((listener) => listener());
}

export function toggleTheme(): void {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const query = media();
  query?.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    query?.removeEventListener("change", listener);
  };
}

/** Тема на экране и выбор устройства; перерисовывает при смене темы системы. */
export function useTheme(): { theme: Theme; chosen: Theme | null; toggle: () => void } {
  const theme = useSyncExternalStore(subscribe, currentTheme, () => "light" as const);
  const chosen = useSyncExternalStore(subscribe, chosenTheme, () => null);
  return { theme, chosen, toggle: toggleTheme };
}
