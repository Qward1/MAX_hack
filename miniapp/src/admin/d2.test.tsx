import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { ChatQuotaPanel } from "./CompanyPages";
import { ColumnChart, QuotaMeter } from "./charts";
import { chooseSurface } from "../site/entry";
import { Landing } from "../site/Landing";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function caps(environment: string, testAuth: boolean) {
  return vi.fn(async () => new Response(JSON.stringify({ environment, features: { test_auth: testAuth } }), { status: 200 }));
}

describe("SITE-ENTRY: корень сайта", () => {
  it("внутри MAX (есть initData) — мини-приложение без запроса", async () => {
    const request = caps("production", false);
    expect(await chooseSurface(() => "query_id=1&hash=x", request)).toBe("miniapp");
    expect(request).not.toHaveBeenCalled();
  });
  it("в обычном браузере на production — лендинг", async () => {
    expect(await chooseSurface(() => "", caps("production", false))).toBe("landing");
  });
  it("тестовый стенд с тестовым входом открывает мини-приложение", async () => {
    expect(await chooseSurface(() => "", caps("test", true))).toBe("miniapp");
    expect(await chooseSurface(() => "", caps("test", false))).toBe("landing");
  });
  it("сбой сети — лендинг; поздние initData всё же дают мини-приложение", async () => {
    expect(await chooseSurface(() => "", vi.fn(async () => { throw new Error("offline"); }))).toBe("landing");
    let data = "";
    const late = vi.fn(async () => { data = "query_id=1"; return new Response("{}", { status: 500 }); });
    expect(await chooseSurface(() => data, late)).toBe("miniapp");
  });
});

describe("Лендинг", () => {
  it("ведёт к заявке УК, входу и боту без выдуманных цифр и отзывов", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ bot_url: "https://max.ru/domsignal_bot" }), { status: 200 })));
    const { container } = render(<Landing />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Проблемы дома — из домового чата в работу");
    expect(screen.getAllByRole("link", { name: "Подключить УК" })[0].getAttribute("href")).toBe("/company/apply");
    expect(screen.getByRole("link", { name: "Вход" }).getAttribute("href")).toBe("/login");
    expect((await screen.findByRole("link", { name: "Открыть бота в MAX" })).getAttribute("href")).toBe("https://max.ru/domsignal_bot");
    expect(screen.getByRole("heading", { name: "Как это работает" })).toBeTruthy();
    expect(container.querySelectorAll(".site-steps > li")).toHaveLength(4);
    const text = container.textContent ?? "";
    expect(text).toContain("Пример: как переписка становится сигналом и заявкой");
    expect(text).not.toMatch(/отзыв|клиент[аоы]в?\b|%|\d{3,}/i);
    expect(text.toLowerCase()).not.toMatch(/тест|демо/);
  });
  it("без ника бота ссылку на бота не показывает", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ bot_url: null }), { status: 200 })));
    render(<Landing />);
    await waitFor(() => expect(screen.queryByRole("link", { name: "Открыть бота в MAX" })).toBeNull());
  });
});

const quota = (limit: number | null, used: number): Schema["ChatQuotaView"] => ({
  limit, used, remaining: limit === null ? null : Math.max(limit - used, 0), over_limit: limit !== null && used > limit, exhausted: limit !== null && used >= limit,
});

describe("Квота чатов", () => {
  it("показывает «N из Q», исчерпание и превышение словами, а не только цветом", () => {
    const { rerender } = render(<QuotaMeter quota={quota(2, 1)} />);
    expect(screen.getByText("1 из 2")).toBeTruthy();
    expect(screen.getByRole("meter").getAttribute("aria-valuenow")).toBe("1");
    rerender(<QuotaMeter quota={quota(2, 2)} />);
    expect(screen.getByText(/новые чаты не подключаются/)).toBeTruthy();
    rerender(<QuotaMeter quota={quota(1, 2)} />);
    expect(screen.getByText(/Квота снижена ниже числа подключённых чатов/)).toBeTruthy();
    rerender(<QuotaMeter quota={quota(null, 3)} />);
    expect(screen.getByText("3, квота без ограничения")).toBeTruthy();
    expect(screen.queryByRole("meter")).toBeNull();
  });

  it("отправляет запрос на расширение с обоснованием и ключом идемпотентности", async () => {
    const request = vi.spyOn(adminClient, "request").mockResolvedValue({});
    const refresh = vi.fn();
    const view = { quota: quota(1, 1), grants: [], requests: [] } as Schema["CompanyQuotaView"];
    const setOpen = vi.fn();
    render(<ChatQuotaPanel base="/api/v1/companies/c1" view={view} refresh={refresh} open setOpen={setOpen} />);
    fireEvent.change(screen.getByLabelText("Сколько чатов добавить"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Обоснование"), { target: { value: "Чаты подъездов 2 и 3" } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить запрос" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [path, init] = request.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/companies/c1/chat-quota/requests");
    expect(JSON.parse(String(init.body))).toEqual({ requested_delta: 2, reason: "Чаты подъездов 2 и 3" });
    expect(new Headers(init.headers).get("Idempotency-Key")).toBeTruthy();
    expect(setOpen).toHaveBeenCalledWith(false);
  });

  it("ответственному не предлагает расширение и отзыв запроса", () => {
    const view = { quota: quota(1, 1), grants: [], requests: [{ id: "r1", company_id: "c1", requested_delta: 1, reason: "x", status: "pending",
      granted_delta: null, decision_reason: null, created_at: "2026-09-24T10:00:00Z", decided_at: null }] } as Schema["CompanyQuotaView"];
    render(<ChatQuotaPanel base="/b" view={view} refresh={() => undefined} open={false} setOpen={() => undefined} canRequest={false} />);
    expect(screen.getByText(/на рассмотрении платформы/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Отозвать запрос" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Запросить расширение" })).toBeNull();
  });
});

describe("Графики", () => {
  it("столбцы с таблицей значений, легендой и пустым состоянием", () => {
    const days = ["2026-09-22", "2026-09-23", "2026-09-24"];
    const { rerender } = render(<ColumnChart title="Заявки по дням" days={days} series={[
      { key: "a", label: "Создано", color: "#235dcc", values: [1, 0, 3] },
      { key: "b", label: "Закрыто", color: "#eb6834", values: [0, 1, 2] },
    ]} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("максимум 3");
    expect(screen.getAllByText("Создано").length).toBeGreaterThan(0);
    fireEvent.focus(screen.getAllByRole("img")[0].querySelectorAll("rect")[2]);
    expect(screen.getByRole("status").textContent).toContain("3");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    rerender(<ColumnChart title="Сигналы" days={days} series={[{ key: "s", label: "Сигналы", color: "#235dcc", values: [0, 0, 0] }]} />);
    expect(screen.getByText("За выбранный период событий нет")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull(); // одна серия — без легенды
  });
});

describe("Страница статуса: уведомления в MAX", () => {
  it("выдаёт одноразовую ссылку на бота и не показывает её до нажатия", async () => {
    const { ApplicationStatus } = await import("./CompanyApply");
    const { ApiClient } = await import("../shared/api/client");
    const view = {
      status: "submitted", short_name: "УК", submitted_at: "2026-09-24T10:00:00Z", requested_chat_count: 2,
      house_addresses: [], messages: [], can_reply: false, decision_reason: null, granted_chat_quota: null,
      quota_unlimited: false, admin_account: "unavailable", max_notifications: false,
    };
    const request = vi.spyOn(ApiClient.prototype, "request").mockImplementation(async (path: string) =>
      path.endsWith("/notify-link") ? { bot_url: "https://max.ru/domsignal_bot?start=ca_abc" } : view);
    render(<ApplicationStatus token={"t".repeat(43)} />);
    expect(await screen.findByRole("heading", { name: "Заявка получена" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Открыть бота в MAX" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Получать уведомления в MAX" }));
    const link = await screen.findByRole("link", { name: "Открыть бота в MAX" });
    expect(link.getAttribute("href")).toBe("https://max.ru/domsignal_bot?start=ca_abc");
    const [path, init] = request.mock.calls.find(([p]) => String(p).endsWith("/notify-link")) as [string, RequestInit];
    expect(path).toBe("/api/v1/onboarding/application-status/notify-link");
    expect(JSON.parse(String(init.body))).toEqual({ token: "t".repeat(43) });
  });
});

describe("Заявка УК: понятные ошибки полей", () => {
  async function fill() {
    const { CompanyApply } = await import("./CompanyApply");
    const { container } = render(<CompanyApply />);
    const field = (name: string, value: string) =>
      fireEvent.change(container.querySelector(`[name="${name}"]`) as HTMLInputElement, { target: { value } });
    field("legal_name", "ООО «Проверка»"); field("short_name", "Проверка"); field("inn", "7712345678");
    field("chats", "2"); field("contact_name", "Иван Петров"); field("email", "test@mail.ru");
    return { field, submit: () => fireEvent.submit(container.querySelector("form") as HTMLFormElement) };
  }

  it("отказ сервера (422) называет поле по-русски, а не общим текстом", async () => {
    const { ApiClient, ApiProblem } = await import("../shared/api/client");
    vi.spyOn(ApiClient.prototype, "request").mockRejectedValue(new ApiProblem({
      type: "about:blank", title: "Request validation failed", status: 422, code: "validation_error",
      detail: "One or more request fields are invalid", retryable: false,
      field_errors: [{ field: "body.contact_email", code: "value_error", message: "Invalid value" }],
    } as never));
    const { submit } = await fill();
    submit();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Проверьте: электронную почту — в виде name@example.ru.");
    expect(alert.textContent).not.toContain("One or more");
  });

  it("короткий адрес ловится до отправки и называет строку", async () => {
    const { ApiClient } = await import("../shared/api/client");
    const request = vi.spyOn(ApiClient.prototype, "request");
    const { field, submit } = await fill();
    field("addresses", "Казань, ул. Баумана, 1\nд. 5");
    submit();
    expect((await screen.findByRole("alert")).textContent).toBe("Адрес в строке 2 слишком короткий: укажите город, улицу и дом.");
    expect(request).not.toHaveBeenCalled();
  });
});

describe("Приглашение при уже открытом входе", () => {
  async function renderWith(destinations: Schema["EmployeeDestinations"]) {
    vi.spyOn(adminClient, "request").mockImplementation(async (path: string) => {
      if (path === "/api/v1/auth/employee/destinations") return destinations;
      throw new Error(`unexpected ${path}`);
    });
    const { InvitationAccept } = await import("./InvitationAccept");
    render(<InvitationAccept token={"i".repeat(43)} />);
  }

  it("администратор платформы не принимает приглашение УК — только отдельный аккаунт", async () => {
    await renderWith({ platform: true, companies: [] });
    expect(await screen.findByRole("button", { name: "Выйти и создать аккаунт сотрудника" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Принять этим аккаунтом" })).toBeNull();
  });

  it("сотрудник выбирает: этим аккаунтом или отдельным", async () => {
    await renderWith({ platform: false, companies: [] });
    expect(await screen.findByRole("button", { name: "Принять этим аккаунтом" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Создать отдельный аккаунт" })).toBeTruthy();
  });
});

describe("Страница статуса до решения", () => {
  it("показывает, сколько чатов запрошено", async () => {
    const { ApplicationStatus } = await import("./CompanyApply");
    const { ApiClient } = await import("../shared/api/client");
    vi.spyOn(ApiClient.prototype, "request").mockResolvedValue({
      status: "under_review", short_name: "УК", submitted_at: "2026-09-24T10:00:00Z", requested_chat_count: 2,
      house_addresses: [], messages: [], can_reply: false, decision_reason: null, granted_chat_quota: null,
      quota_unlimited: false, admin_account: "unavailable", max_notifications: true,
    });
    render(<ApplicationStatus token={"t".repeat(43)} />);
    expect(await screen.findByText("Запрошено: 2 чата. Итоговую квоту назначит платформа.")).toBeTruthy();
  });
});
