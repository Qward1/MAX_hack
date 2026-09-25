import { render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ticketClient } from "../shared/api/tickets";
import { EmployeeGate } from "./EmployeeGate";

afterEach(() => { vi.restoreAllMocks(); });

function signedIn(destinations: { platform: boolean; companies: { company_id: string; name: string }[] }) {
  vi.spyOn(ticketClient, "capabilities").mockResolvedValue({ environment: "production", features: {} } as never);
  vi.spyOn(ticketClient, "employeeSession").mockResolvedValue({ stage: "authenticated" } as never);
  return vi.spyOn(ticketClient, "request").mockImplementation(async (path: string) => {
    if (path === "/api/v1/auth/employee/destinations") return destinations as never;
    throw new Error(`unexpected ${path}`);
  });
}

describe("Вход сотрудника на странице платформы (живая проверка D3)", () => {
  it("сотрудник УК получает переход в свой кабинет, а не «доступ отозван»", async () => {
    signedIn({ platform: false, companies: [{ company_id: "c1", name: "УК Первая" }] });
    render(<EmployeeGate platform><p>Платформа</p></EmployeeGate>);
    await screen.findByText("Платформа");
    // Как `platform/bootstrap` → 403 у сотрудника без роли платформы.
    act(() => { window.dispatchEvent(new CustomEvent("employee-access-lost", { detail: 403 })); });
    const link = await screen.findByRole("link", { name: "Открыть кабинет управляющей компании" });
    expect(link.getAttribute("href")).toBe("/admin/");
    expect(screen.queryByText("Доступ отозван или ограничен")).toBeNull();
  });

  it("без кабинета УК — прежнее честное «доступ отозван»", async () => {
    signedIn({ platform: false, companies: [] });
    render(<EmployeeGate platform><p>Платформа</p></EmployeeGate>);
    await screen.findByText("Платформа");
    act(() => { window.dispatchEvent(new CustomEvent("employee-access-lost", { detail: 403 })); });
    expect(await screen.findByText("Доступ отозван или ограничен")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Открыть кабинет управляющей компании" })).toBeNull();
  });
});
