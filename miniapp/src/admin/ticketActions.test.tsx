import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Me } from "../shared/api/client";
import type { Ticket, TicketClient } from "../shared/api/tickets";
import { incident } from "../test/fixtures";
import { TicketDetail } from "./TicketDetail";

// jsdom не умеет модальный <dialog>: достаточно открыть и закрыть его атрибутом.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute("open"); };

const HOUSE = incident.house_id;
const me: Me = {
  id: "user-admin",
  display_name: "A16 admin",
  houses: [{ id: HOUSE, name: "Дом", address: "Казань, Синтетическая улица, 1", role: "company_admin", is_demo: true }],
} as unknown as Me;
const responsible = { user_id: "user-responsible", display_name: "A16 responsible" };

function ticket(patch: Partial<Ticket>): Ticket {
  return {
    id: "ticket-1",
    internal_number: "T-1",
    incident_id: incident.id,
    house_id: HOUSE,
    management_id: "management-1",
    status: "new",
    version: 1,
    assignee_id: null,
    assignee_name: null,
    accepted_by: null,
    accepted_at: null,
    requires_reassignment: false,
    routing_reason: "default",
    responsibility: "not_verified",
    source: "api",
    created_by: "user-resident",
    created_at: "2026-09-27T10:00:00Z",
    updated_at: "2026-09-27T10:00:00Z",
    latest_attempt: null,
    observation_conflict: false,
    deadlines: [],
    allowed_actions: [],
    ...patch,
  } as Ticket;
}

function show(value: Ticket, viewer: Me = me) {
  const page = { limit: 20, offset: 0, total: 0 };
  const client = {
    ticket: vi.fn().mockResolvedValue(value),
    incident: vi.fn().mockResolvedValue(incident),
    events: vi.fn().mockResolvedValue({ items: [], page }),
    attempts: vi.fn().mockResolvedValue({ items: [], page }),
    assignees: vi.fn().mockResolvedValue({ items: [responsible, { user_id: "user-operator", display_name: "A16 operator" }], page: { ...page, total: 2 } }),
    command: vi.fn(),
  } as unknown as TicketClient;
  render(<TicketDetail client={client} id={value.id} me={viewer} revision={0} navigate={vi.fn()} />);
  return client;
}

async function panel() {
  return within((await screen.findByRole("heading", { name: "Действия по заявке" })).closest("section")!);
}

describe("RA-04 действие с исполнителем", () => {
  it("при указанном исполнителе — «Изменить исполнителя» среди других действий, и шаг за исполнителем", async () => {
    show(ticket({
      assignee_id: responsible.user_id,
      assignee_name: responsible.display_name,
      allowed_actions: ["assign", "clarify", "wait-external", "cancel"],
    }));
    const actions = await panel();
    expect(actions.queryByRole("button", { name: "Назначить исполнителя" })).toBeNull();
    const change = actions.getByRole("button", { name: "Изменить исполнителя" });
    // Не основное действие: сотрудник видит, что назначение уже сделано.
    expect(change.className).toContain("ds-btn-secondary");
    expect(actions.getByText("Доступные действия")).toBeTruthy();
    const buttons = actions.getAllByRole("button").map((button) => button.textContent);
    expect(buttons.indexOf("Изменить исполнителя")).toBeLessThan(buttons.indexOf("Запросить уточнение"));
    expect(screen.getByText("Исполнитель назначен и должен принять заявку.")).toBeTruthy();
    expect(screen.queryByText("Назначьте исполнителя или возьмите в работу.")).toBeNull();

    fireEvent.click(change);
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "Изменить исполнителя" })).toBeTruthy();
    expect(await dialog.findByText("Сейчас: A16 responsible")).toBeTruthy();
    expect(dialog.getByRole("radio", { name: /Без исполнителя/ })).toBeTruthy();
    expect(dialog.getByRole("button", { name: "Изменить исполнителя" })).toBeTruthy();
  });

  it("без исполнителя назначение остаётся основным действием", async () => {
    show(ticket({ allowed_actions: ["assign", "clarify", "cancel"] }));
    const actions = await panel();
    expect(actions.getByRole("button", { name: "Назначить исполнителя" }).className).toContain("ds-btn-primary");
    expect(screen.getByText("Назначьте исполнителя или возьмите в работу.")).toBeTruthy();
  });

  it("исполнитель сам видит принятие основным, замену — среди других", async () => {
    const assignee: Me = { ...me, id: responsible.user_id, display_name: responsible.display_name };
    show(ticket({
      assignee_id: responsible.user_id,
      assignee_name: responsible.display_name,
      allowed_actions: ["assign", "accept", "clarify", "cancel"],
    }), assignee);
    const actions = await panel();
    expect(actions.getByRole("button", { name: "Принять заявку" }).className).toContain("ds-btn-primary");
    expect(actions.getByRole("button", { name: "Изменить исполнителя" }).className).toContain("ds-btn-secondary");
  });

  it("без исполнителя «взять в работу» — основное, назначение — первым из других", async () => {
    show(ticket({ allowed_actions: ["assign", "accept", "clarify", "cancel"] }));
    const actions = await panel();
    expect(actions.getByRole("button", { name: "Взять в работу" }).className).toContain("ds-btn-primary");
    expect(actions.getByRole("button", { name: "Назначить исполнителя" }).className).toContain("ds-btn-secondary");
  });

  it("исполнителя нужно заменить — замена снова основное действие", async () => {
    show(ticket({
      assignee_id: responsible.user_id,
      assignee_name: responsible.display_name,
      requires_reassignment: true,
      allowed_actions: ["assign", "clarify", "cancel"],
    }));
    const actions = await panel();
    expect(actions.getByRole("button", { name: "Изменить исполнителя" }).className).toContain("ds-btn-primary");
  });
});
