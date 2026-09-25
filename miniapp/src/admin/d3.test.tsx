import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { ChatSettingsPanel, Mailings, SERVICE_ONLY_RULE } from "./CommunityPages";

afterEach(() => { vi.restoreAllMocks(); });

const BASE = "/api/v1/companies/c1";
const draft: Schema["BroadcastView"] = {
  id: "b1", origin: "company", company_id: "c1", kind: "announcement", topic: "works", title: "Промывка отопления",
  body: "28 сентября с 10:00 до 14:00.", audience: { mode: "all", only_with_chat: false, only_open_access: false },
  channels: ["chat", "feed"], status: "draft", created_at: "2026-09-27T07:00:00Z", version: 1,
  author_name: "Администратор", sender: "Сообщение от УК «УК Первая»", allowed_actions: ["edit", "preview", "confirm", "cancel"],
};

function route(handlers: Record<string, (init?: RequestInit) => unknown>) {
  return vi.spyOn(adminClient, "request").mockImplementation(async (path: string, init?: RequestInit) => {
    const key = Object.keys(handlers).find(prefix => path.startsWith(prefix));
    if (!key) throw new Error(`unexpected ${path}`);
    return handlers[key](init) as never;
  });
}

describe("Рассылки в кабинете", () => {
  it("черновик → предпросмотр получателей → подтверждение с правилом «не реклама»", async () => {
    let status = "draft";
    const request = route({
      [`${BASE}/broadcasts?`]: () => ({ items: [{ id: "b1", kind: "announcement", title: draft.title, status,
        created_at: draft.created_at }], page: { limit: 20, offset: 0, total: 1 } }),
      "/api/v1/broadcasts/b1/preview": () => ({ houses: 2, companies: 0, channels: [
        { channel: "chat", targets: 2, will_send: 1, skipped: { CHAT_SETTING_OFF: 1 } },
        { channel: "feed", targets: 2, will_send: 2, skipped: {} }] }),
      "/api/v1/broadcasts/b1/confirm": () => { status = "scheduled"; return { ...draft, status, version: 2 }; },
      "/api/v1/broadcasts/b1": () => ({ ...draft, status }),
    });
    render(<Mailings base={BASE} />);
    fireEvent.click(await screen.findByRole("button", { name: draft.title }));
    expect(await screen.findByText(draft.body)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр получателей" }));
    expect(await screen.findByText("Домов в аудитории: 2")).toBeTruthy();
    expect(screen.getByText("выключено в настройках чата: 1")).toBeTruthy();
    const send = screen.getByRole("button", { name: "Подтвердить и отправить" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Это сервисное сообщение для жителей, не реклама"));
    fireEvent.click(send);
    await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/broadcasts/b1/confirm", expect.objectContaining({ method: "POST" })));
    const body = JSON.parse(String(request.mock.calls.find(call => call[0] === "/api/v1/broadcasts/b1/confirm")![1]!.body));
    expect(body).toEqual({ expected_version: 1, service_only: true });
  });

  it("форма нового сообщения показывает правило и собирает опрос", async () => {
    const request = route({
      [`${BASE}/broadcasts?`]: () => ({ items: [], page: { limit: 20, offset: 0, total: 0 } }),
      [`${BASE}/broadcast-houses`]: () => [{ house_id: "h1", address: "Казань, 1", has_chat: true, open_access: false }],
      "/api/v1/capabilities": () => ({}),
      [`${BASE}/broadcasts`]: () => ({ ...draft, id: "b2", kind: "poll" }),
      "/api/v1/broadcasts/b2": () => ({ ...draft, id: "b2", kind: "poll" }),
    });
    render(<Mailings base={BASE} />);
    fireEvent.click(await screen.findByRole("button", { name: "Новое сообщение" }));
    expect(screen.getByText(SERVICE_ONLY_RULE)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Опрос"));
    fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "Покраска подъезда" } });
    fireEvent.change(screen.getByLabelText("Вопрос"), { target: { value: "Какой цвет выбрать?" } });
    fireEvent.change(screen.getByLabelText("Вариант 1"), { target: { value: "Бежевый" } });
    fireEvent.change(screen.getByLabelText("Вариант 2"), { target: { value: "Серый" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith(`${BASE}/broadcasts`, expect.objectContaining({ method: "POST" })));
    const call = request.mock.calls.find(c => c[0] === `${BASE}/broadcasts`)!;
    const body = JSON.parse(String(call[1]!.body));
    expect(body.kind).toBe("poll");
    expect(body.poll.options).toEqual(["Бежевый", "Серый"]);
    expect(new Headers(call[1]!.headers).get("Idempotency-Key")).toBeTruthy();
  });
});

describe("Рассылки: находки живой проверки D3", () => {
  const sent: Schema["BroadcastView"] = {
    ...draft, status: "sent", version: 3, sent_at: "2026-09-27T07:05:00Z", allowed_actions: ["edit_content", "retract"],
    stats: [{ channel: "chat", total: 1, accepted: 1, failed: 0, unknown: 0, pending: 0, deferred_quiet_hours: 0, skipped: {} }],
  };
  const list = () => ({ items: [{ id: "b1", kind: "announcement", title: draft.title, status: "sent", created_at: draft.created_at }],
    page: { limit: 20, offset: 0, total: 1 } });

  it("«Сейчас»: карточка сама доходит до «Отправлено» и «Исправить текст», без возврата к списку", async () => {
    let state: "draft" | "scheduled" | "sent" = "draft";
    route({
      [`${BASE}/broadcasts?`]: list,
      "/api/v1/broadcasts/b1/confirm": () => { state = "scheduled"; return { ...draft, status: "scheduled", version: 2 }; },
      "/api/v1/broadcasts/b1": () => {
        if (state === "scheduled") {
          state = "sent"; // воркер отправил сразу после первого чтения
          return { ...draft, status: "scheduled", version: 2, scheduled_at: new Date().toISOString(), allowed_actions: ["cancel"] };
        }
        return state === "sent" ? sent : draft;
      },
    });
    render(<Mailings base={BASE} />);
    fireEvent.click(await screen.findByRole("button", { name: draft.title }));
    fireEvent.click(await screen.findByLabelText("Это сервисное сообщение для жителей, не реклама"));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить и отправить" }));
    expect(await screen.findByRole("button", { name: "Исправить текст" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Статистика отправки" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Отменить отправку" })).toBeNull();
  });

  it("отказ «уже отправлено» сразу показывает актуальное состояние", async () => {
    const { ApiProblem } = await import("../shared/api/client");
    let reads = 0;
    route({
      [`${BASE}/broadcasts?`]: list,
      "/api/v1/broadcasts/b1/cancel": () => {
        throw new ApiProblem({ type: "about:blank", title: "Conflict", status: 409, code: "conflict", retryable: false,
          detail: "Сообщение уже отправлено — отменить нельзя. Его можно удалить.", trace_id: "t" } as never);
      },
      // Первое чтение устарело (ещё «Запланировано» в будущем), следующее — актуальное.
      "/api/v1/broadcasts/b1": () => (reads++ === 0
        ? { ...draft, status: "scheduled", version: 2, scheduled_at: "2099-01-01T00:00:00Z", allowed_actions: ["cancel"] }
        : sent),
    });
    render(<Mailings base={BASE} />);
    fireEvent.click(await screen.findByRole("button", { name: draft.title }));
    fireEvent.click(await screen.findByRole("button", { name: "Отменить отправку" }));
    expect(await screen.findByRole("button", { name: "Исправить текст" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Сообщение уже отправлено — отменить нельзя. Его можно удалить.");
  });

  it("правило сервера для опроса видно в форме, а не общий текст", async () => {
    const { ApiProblem } = await import("../shared/api/client");
    route({
      [`${BASE}/broadcasts?`]: () => ({ items: [], page: { limit: 20, offset: 0, total: 0 } }),
      [`${BASE}/broadcast-houses`]: () => [{ house_id: "h1", address: "Казань, 1", has_chat: true, open_access: false }],
      "/api/v1/capabilities": () => ({}),
      [`${BASE}/broadcasts`]: () => {
        throw new ApiProblem({ type: "about:blank", title: "Request validation failed", status: 422, code: "validation_error",
          detail: "Опрос должен быть открыт хотя бы 10 минут", retryable: false, trace_id: "t",
          field_errors: [{ field: "poll", code: "invalid_choice", message: "Опрос должен быть открыт хотя бы 10 минут" }] } as never);
      },
    });
    render(<Mailings base={BASE} />);
    fireEvent.click(await screen.findByRole("button", { name: "Новое сообщение" }));
    fireEvent.click(screen.getByLabelText("Опрос"));
    fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "Проверка опроса" } });
    fireEvent.change(screen.getByLabelText("Вопрос"), { target: { value: "Удобно ли время уборки?" } });
    fireEvent.change(screen.getByLabelText("Вариант 1"), { target: { value: "Да" } });
    fireEvent.change(screen.getByLabelText("Вариант 2"), { target: { value: "Нет" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Опрос должен быть открыт хотя бы 10 минут");
  });

  it("ошибка схемы называет поле формы рассылки", async () => {
    const { ApiProblem } = await import("../shared/api/client");
    route({
      [`${BASE}/broadcasts?`]: () => ({ items: [], page: { limit: 20, offset: 0, total: 0 } }),
      [`${BASE}/broadcast-houses`]: () => [],
      "/api/v1/capabilities": () => ({}),
      [`${BASE}/broadcasts`]: () => {
        throw new ApiProblem({ type: "about:blank", title: "Request validation failed", status: 422, code: "validation_error",
          detail: "One or more request fields are invalid", retryable: false, trace_id: "t",
          field_errors: [{ field: "body.poll.options", code: "value_error", message: "Invalid value" }] } as never);
      },
    });
    render(<Mailings base={BASE} />);
    fireEvent.click(await screen.findByRole("button", { name: "Новое сообщение" }));
    fireEvent.click(screen.getByLabelText("Опрос"));
    fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "Проверка опроса" } });
    fireEvent.change(screen.getByLabelText("Вопрос"), { target: { value: "Удобно ли время уборки?" } });
    fireEvent.change(screen.getByLabelText("Вариант 1"), { target: { value: "Да" } });
    fireEvent.change(screen.getByLabelText("Вариант 2"), { target: { value: "да" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Проверьте: вопрос, варианты (без повторов) и срок опроса.");
  });
});

describe("Настройки бота в чате", () => {
  it("памятка не отключается, изменения сохраняются, история видна", async () => {
    const view: Schema["ChatSettingsView"] = {
      binding_id: "cb1", post_ticket_status: true, post_company_messages: true, post_polls: true,
      post_platform_messages: false, quiet_start: "22:00", quiet_end: "08:00", can_edit: true,
      history: [{ occurred_at: "2026-09-27T07:00:00Z", actor_name: "Администратор", summary: "Опросы: выключены" }],
    };
    const request = route({ "/api/v1/chat-bindings/cb1/settings": () => view });
    render(<ChatSettingsPanel bindingId="cb1" />);
    fireEvent.click(screen.getByText("Что бот публикует в этом чате"));
    expect(await screen.findByText(/Памятка безопасности и сообщение о чтении чата не отключаются/)).toBeTruthy();
    expect(screen.getByText("Опросы: выключены")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Сообщения платформы ДомСигнал"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить настройки" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/chat-bindings/cb1/settings", expect.objectContaining({ method: "POST" })));
    const call = request.mock.calls.find(c => c[1]?.method === "POST")!;
    expect(JSON.parse(String(call[1]!.body)).post_platform_messages).toBe(true);
  });
});
