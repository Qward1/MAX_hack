import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SHOWCASE_NOTE, ShowcaseLock, type Schema } from "./administration";
import { OpenAccessSwitch, PassiveSwitch } from "./CompanyPages";

afterEach(() => vi.restoreAllMocks());

const house = (open: boolean) => ({
  house_id: "h1", management_id: "m1", address: "Казань, Синтетическая улица, 1", valid_from: "2026-09-01T00:00:00Z",
  open_resident_access: open, bindings: [], connection_requests: [],
}) as unknown as Schema["CompanyHouseView"];
const binding = { id: "b1", title: "Дом", max_chat_id: "c1", status: "active", scope_type: "house", scope_value: null,
  suspension_reason: null, passive_capture_enabled: true } as Schema["ChatSummary"];
const noop = async () => {};

describe("Проверочный аккаунт в демо-УК (F1 §5.5)", () => {
  it("открытый доступ не выключить: кнопка неактивна, рядом пояснение", () => {
    render(<ShowcaseLock.Provider value><OpenAccessSwitch base="/api/v1/companies/c1" house={house(true)} refresh={() => {}} /></ShowcaseLock.Provider>);
    expect((screen.getByRole("button", { name: "Выключить открытый доступ" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(SHOWCASE_NOTE)).toBeTruthy();
  });

  it("включить открытый доступ можно — это не ломает витрину", () => {
    render(<ShowcaseLock.Provider value><OpenAccessSwitch base="/api/v1/companies/c1" house={house(false)} refresh={() => {}} /></ShowcaseLock.Provider>);
    expect((screen.getByRole("button", { name: "Включить открытый доступ" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(SHOWCASE_NOTE)).toBeNull();
  });

  it("чтение демо-чата не выключить", () => {
    render(<ShowcaseLock.Provider value>
      <PassiveSwitch binding={binding} available aiAnalysis busy={false} confirming={false} ask={() => {}} cancel={() => {}} change={noop} />
    </ShowcaseLock.Provider>);
    expect((screen.getByRole("button", { name: "Выключить чтение чата" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(SHOWCASE_NOTE)).toBeTruthy();
  });

  it("обычный администратор ничего не теряет", () => {
    render(<OpenAccessSwitch base="/api/v1/companies/c1" house={house(true)} refresh={() => {}} />);
    expect((screen.getByRole("button", { name: "Выключить открытый доступ" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(SHOWCASE_NOTE)).toBeNull();
  });
});
