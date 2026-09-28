import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { chosenTheme, currentTheme, setTheme } from "../theme";
import { ThemeToggle } from "./ThemeToggle";

const root = document.documentElement;

function systemDark(matches: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({ matches, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() }) as unknown as MediaQueryList,
  );
}

afterEach(() => {
  delete root.dataset.theme;
  window.localStorage.removeItem("ds:theme");
  systemDark(false);
});

describe("тема устройства", () => {
  it("без выбора следует системе и ничего не пишет в хранилище", () => {
    systemDark(true);
    expect(chosenTheme()).toBeNull();
    expect(currentTheme()).toBe("dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Включить светлую тему" })).toBeTruthy();
    expect(root.dataset.theme).toBeUndefined();
    expect(window.localStorage.getItem("ds:theme")).toBeNull();
  });

  it("кнопка переключает тему, запоминает выбор и меняет подпись", () => {
    systemDark(false);
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Включить тёмную тему" }));
    expect(root.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("ds:theme")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "Включить светлую тему" }));
    expect(root.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("ds:theme")).toBe("light");
    expect(screen.getByRole("button", { name: "Включить тёмную тему" })).toBeTruthy();
  });

  it("выбор светлой темы сильнее тёмной темы системы", () => {
    systemDark(true);
    setTheme("light");
    expect(currentTheme()).toBe("light");
    render(<ThemeToggle labelled />);
    // Кнопка с видимой подписью — для листа «Разделы» на телефоне.
    expect(screen.getByRole("button", { name: "Включить тёмную тему" }).textContent).toBe("Включить тёмную тему");
  });

  it("сохранённый выбор читается, если атрибут ещё не поставлен", () => {
    window.localStorage.setItem("ds:theme", "dark");
    expect(chosenTheme()).toBe("dark");
    window.localStorage.setItem("ds:theme", "blue");
    expect(chosenTheme()).toBeNull();
  });

  it("недоступное хранилище не ломает переключение", () => {
    systemDark(false);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Включить тёмную тему" }));
    expect(root.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Включить светлую тему" })).toBeTruthy();
  });
});
