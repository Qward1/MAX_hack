import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { ChatConnections } from "./CompanyPages";

afterEach(() => vi.restoreAllMocks());

const BASE = "/api/v1/companies/c1";
const request = (patch: Partial<Schema["ConnectionView"]>): Schema["ConnectionView"] => ({
  id: "r1", house_id: "h1", status: "chat_detected", candidate_max_chat_id: "chat-1", last_error_code: null,
  expires_at: "2026-09-29T12:00:00Z", scope_type: "house", scope_value: null, ...patch,
});
const house = (connection: Schema["ConnectionView"]) => ({
  house_id: "h1", management_id: "m1", address: "Казань, Синтетическая улица, 1", valid_from: "2026-09-01T00:00:00Z",
  can_connect_chats: true, bindings: [], connection_requests: [connection],
}) as unknown as Schema["CompanyHouseView"];

function route(connection: Schema["ConnectionView"]) {
  return vi.spyOn(adminClient, "request").mockImplementation(async (path: string) => {
    if (path === `${BASE}/houses`) return [house(connection)] as never;
    if (path === `${BASE}/chat-quota`) return { quota: { used: 0, limit: 1, remaining: 1, exhausted: false, over_limit: false }, grants: [], requests: [] } as never;
    if (path === "/api/v1/capabilities") return { features: { passive_capture: true }, bot_url: null } as never;
    return {} as never;
  });
}

describe("Подключение чата: повторная проверка после ошибки (F1)", () => {
  it("бот без прав администратора: ошибка видна, «Подтвердить подключение» остаётся и проверяет заново", async () => {
    const calls = route(request({ last_error_code: "bot_permission_missing" }));
    render(<ChatConnections base={BASE} />);
    expect(await screen.findByText(/Боту не выданы права администратора с чтением сообщений/)).toBeTruthy();
    expect(screen.getByText(/нажмите «Подтвердить подключение» — проверка пройдёт заново/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить подключение" }));
    await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/chat-connections/r1/approve", expect.objectContaining({ method: "POST" })));
  });

  it("бот ещё не в группе — кнопки нет, есть подсказка", async () => {
    route(request({ status: "connector_claimed", candidate_max_chat_id: null }));
    render(<ChatConnections base={BASE} />);
    expect(await screen.findByText("Кнопка появится, когда бот будет в группе с нужными правами.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Подтвердить подключение" })).toBeNull();
  });
});
