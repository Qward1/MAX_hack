import { MaxUI } from "@maxhub/max-ui";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { apiWith, deferred, error, house, incident } from "../test/fixtures";
import { type IncidentDetail } from "../shared/api/client";
import { App } from "./App";

describe("board/detail experience", () => {
  it("does not copy launch/auth parameters into incident links", async () => {
    window.history.replaceState(
      null,
      "",
      "/?WebAppData=test-only-secret#launch-secret",
    );
    render(<App client={apiWith()} />);
    const link = await screen.findByRole("link", { name: /Открыть:/ });
    expect(link.getAttribute("href")).not.toContain("secret");
    expect(link.getAttribute("href")).not.toContain("WebAppData");
  });
  it.each([false, true])(
    "does not request a capability-disabled screen (detail=%s)",
    async (detail) => {
      const client = apiWith();
      const capabilities = await client.capabilities();
      vi.mocked(client.capabilities).mockResolvedValue({
        ...capabilities,
        features: {
          ...capabilities.features,
          incident_board: false,
          incident_detail: false,
        },
      });
      if (detail)
        window.history.replaceState(null, "", `/?incident=${incident.id}`);
      render(<App client={client} />);
      await screen.findByText("Этот раздел сейчас отключён");
      expect(client.incidents).not.toHaveBeenCalled();
      expect(client.incident).not.toHaveBeenCalled();
    },
  );
  it("loads board from API and preserves order for 100 incidents", async () => {
    const items = Array.from({ length: 100 }, (_, i) => ({
      ...incident,
      id: String(i),
      title: `Проблема ${i}`,
    }));
    render(<App client={apiWith(items)} />);
    const links = await screen.findAllByRole("link", { name: /Открыть:/ });
    expect(links).toHaveLength(100);
    expect(links[0].textContent).toContain("Открыть");
    expect(links[99].getAttribute("aria-label")).toBe("Открыть: Проблема 99");
  });
  it.each([401, 403, 404])(
    "shows safe %i without leaking prior private data",
    async (status) => {
      const client = apiWith();
      render(<App client={client} />);
      await screen.findByText(house.address);
      vi.mocked(client.incidents).mockRejectedValueOnce(error(status));
      fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
      await waitFor(() => expect(screen.queryByText(house.address)).toBeNull());
      expect(screen.queryByText("PRIVATE")).toBeNull();
      expect(screen.queryByText("Попробовать снова")).toBeNull();
    },
  );
  it("initial network failure can be retried", async () => {
    const client = apiWith();
    vi.mocked(client.incidents).mockRejectedValueOnce(new Error("network"));
    render(<App client={client} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Попробовать снова" }),
    );
    expect(await screen.findByRole("link", { name: /Открыть:/ })).toBeTruthy();
  });
  it("retains stale data after refetch failure, then reloads from server", async () => {
    const client = apiWith();
    render(<App client={client} />);
    await screen.findByText(house.address);
    vi.mocked(client.incidents).mockRejectedValueOnce(error(503));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText(/Показаны ранее загруженные/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Открыть:/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() =>
      expect(screen.queryByText(/Показаны ранее загруженные/)).toBeNull(),
    );
    expect(client.incidents).toHaveBeenCalledTimes(3);
  });
  it("navigates by keyboard to detail, restores detail after remount and offers browser back", async () => {
    const user = userEvent.setup();
    const client = apiWith();
    const mounted = render(
      <MaxUI>
        <App client={client} />
      </MaxUI>,
    );
    const link = await screen.findByRole("link", { name: /Открыть:/ });
    link.focus();
    await user.keyboard("{Enter}");
    await screen.findByText("Что делать сейчас");
    expect(new URL(window.location.href).searchParams.get("incident")).toBe(
      incident.id,
    );
    expect(document.activeElement?.id).toBe("page-title");
    mounted.unmount();
    render(<App client={client} />);
    await screen.findByText("Что делать сейчас");
    expect(client.incident).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: /К доске дома/ }));
    expect(await screen.findByRole("link", { name: /Открыть:/ })).toBeTruthy();
  });
  it("ignores late responses after navigation and cancels pending requests", async () => {
    const pending = deferred<IncidentDetail>();
    const client = apiWith();
    vi.mocked(client.incident).mockReturnValueOnce(pending.promise);
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole("link", { name: /Открыть:/ }));
    await screen.findByText("Загрузка проблемы");
    const signal = vi.mocked(client.incident).mock.calls[0]?.[1];
    await act(async () => {
      window.history.replaceState(null, "", "/");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await screen.findByRole("link", { name: /Открыть:/ });
    expect(signal?.aborted).toBe(true);
    await act(async () =>
      pending.resolve({ ...incident, title: "OLD PRIVATE DETAIL" }),
    );
    expect(screen.queryByText("OLD PRIVATE DETAIL")).toBeNull();
  });
  it("supports nullable fields and future enums without fabricating route or action", async () => {
    window.history.replaceState(null, "", `/?incident=${incident.id}`);
    const future = {
      ...incident,
      status: "future",
      category: "future",
      rule: null,
      reports: [],
      description: "",
      allowed_actions: [{ code: "future", enabled: true }],
    } as unknown as IncidentDetail;
    render(<App client={apiWith([future])} />);
    expect(await screen.findByText("Состояние обновилось")).toBeTruthy();
    expect(screen.getByText("Не определён")).toBeTruthy();
    expect(screen.queryByText("Официальный источник")).toBeNull();
    expect(screen.queryByRole("button", { name: "future" })).toBeNull();
  });
  it("reported is explicitly a resident assertion", async () => {
    window.history.replaceState(null, "", `/?incident=${incident.id}`);
    render(<App client={apiWith([{ ...incident, status: "reported" }])} />);
    expect(
      await screen.findByText(
        /Регистрация во внешней системе ДомСигналом не подтверждена/,
      ),
    ).toBeTruthy();
  });
  it("uses a received retry descriptor, not status, for NextAction", async () => {
    window.history.replaceState(null, "", `/?incident=${incident.id}`);
    const detail = {
      ...incident,
      allowed_actions: [{ code: "retry", enabled: true, reason: null }],
    } as unknown as IncidentDetail;
    const client = apiWith([detail]);
    render(<App client={client} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Обновить данные" }),
    );
    await waitFor(() => expect(client.incident).toHaveBeenCalledTimes(2));
  });
  it("marks backgrounded data stale", async () => {
    render(<App client={apiWith()} />);
    await screen.findByText(house.address);
    fireEvent(document, new Event("visibilitychange"));
    expect(await screen.findByText("Данные могли измениться.")).toBeTruthy();
  });
  it("a selected foreign house does not show the default house", async () => {
    window.history.replaceState(null, "", "/?house=foreign");
    const client = apiWith();
    render(<App client={client} />);
    await screen.findByText("Нет доступа к этому дому");
    expect(client.incidents).not.toHaveBeenCalled();
    expect(screen.queryByText(house.address)).toBeNull();
  });
  it("keeps manual foundation report and reuses idempotency key after ambiguous failure", async () => {
    const client = apiWith([]);
    vi.mocked(client.createReport).mockRejectedValueOnce(new Error("network"));
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: "Сообщить" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Описание" }), {
      target: { value: "Не работает лифт" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить сигнал" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить сигнал" }));
    await waitFor(() => expect(client.createReport).toHaveBeenCalledTimes(2));
    expect(vi.mocked(client.createReport).mock.calls[0][1]).toBe(
      vi.mocked(client.createReport).mock.calls[1][1],
    );
  });
});
