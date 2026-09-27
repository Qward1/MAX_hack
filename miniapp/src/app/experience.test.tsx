import { MaxUI } from "@maxhub/max-ui";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  actionCard,
  apiWith,
  deferred,
  draft,
  error,
  house,
  incident,
  outcome,
} from "../test/fixtures";
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
    const link = await screen.findByRole("link", { name: new RegExp(incident.title) });
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
      await screen.findByText("Этот раздел сейчас выключен");
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
    const list = await screen.findByRole("list", { name: "Проблемы дома" });
    const links = within(list).getAllByRole("link");
    expect(links).toHaveLength(100);
    expect(links[0].textContent).toContain("Проблема 0");
    expect(links[99].textContent).toContain("Проблема 99");
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
      expect(screen.queryByRole("button", { name: "Повторить" })).toBeNull();
    },
  );
  it("initial network failure can be retried", async () => {
    const client = apiWith();
    vi.mocked(client.incidents).mockRejectedValueOnce(new Error("network"));
    render(<App client={client} />);
    expect(await screen.findByText("Не удалось загрузить проблемы дома")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("link", { name: new RegExp(incident.title) })).toBeTruthy();
  });
  it("retains stale data after refetch failure, then reloads from server", async () => {
    const client = apiWith();
    render(<App client={client} />);
    await screen.findByText(house.address);
    vi.mocked(client.incidents).mockRejectedValueOnce(error(503));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText(/Показаны данные, загруженные раньше/)).toBeTruthy();
    expect(screen.getByRole("link", { name: new RegExp(incident.title) })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() =>
      expect(screen.queryByText(/Показаны данные, загруженные раньше/)).toBeNull(),
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
    const link = await screen.findByRole("link", { name: new RegExp(incident.title) });
    link.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("heading", { name: "Что известно" });
    expect(new URL(window.location.href).searchParams.get("incident")).toBe(
      incident.id,
    );
    expect(document.activeElement?.id).toBe("page-title");
    mounted.unmount();
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "Что известно" });
    expect(client.incident).toHaveBeenCalledTimes(2);
    // После перезагрузки истории внутри приложения нет: «Назад» ведёт к проблемам дома.
    fireEvent.click(screen.getByRole("button", { name: /Назад/ }));
    expect(await screen.findByRole("link", { name: new RegExp(incident.title) })).toBeTruthy();
  });
  it("ignores late responses after navigation and cancels pending requests", async () => {
    const pending = deferred<IncidentDetail>();
    const client = apiWith();
    vi.mocked(client.incident).mockReturnValueOnce(pending.promise);
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole("link", { name: new RegExp(incident.title) }));
    await screen.findByText("Загружаем проблему");
    const signal = vi.mocked(client.incident).mock.calls[0]?.[1];
    await act(async () => {
      window.history.replaceState(null, "", "/");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await screen.findByRole("link", { name: new RegExp(incident.title) });
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
    // Срока нет — строки «Срок» нет, и он не выдумывается.
    expect(screen.queryByText("Срок")).toBeNull();
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
  it.each(["foreign", ""])("invalid house selector %s does not show the default house", async (selector) => {
    window.history.replaceState(null, "", `/?house=${selector}`);
    const client = apiWith();
    render(<App client={client} />);
    await screen.findByText("Нет доступа к этому дому");
    expect(client.incidents).not.toHaveBeenCalled();
    expect(screen.queryByText(house.address)).toBeNull();
  });
  it("with several houses asks which house first, then remembers it and offers a switcher (D-01)", async () => {
    window.localStorage.clear();
    const client = apiWith();
    vi.mocked(client.me).mockResolvedValue({
      ...(await client.me()), houses: [house, { ...house, id: "second", address: "Второй дом" }],
    });
    const view = render(<App client={client} />);
    await screen.findByRole("heading", { name: "Выберите дом" });
    expect(client.incidents).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("link", { name: /Второй дом/ }));
    await waitFor(() => expect(client.incidents).toHaveBeenCalledWith("second", expect.any(AbortSignal), 0, "open"));
    const switcher = await screen.findByRole("button", { name: "Дом Второй дом" });
    fireEvent.click(switcher);
    fireEvent.click(screen.getByRole("option", { name: house.address }));
    await waitFor(() => expect(client.incidents).toHaveBeenCalledWith(house.id, expect.any(AbortSignal), 0, "open"));
    view.unmount();
    // Следующий запуск без выбора — последний дом этого устройства.
    window.history.replaceState(null, "", "/");
    vi.mocked(client.incidents).mockClear();
    render(<App client={client} />);
    await waitFor(() => expect(client.incidents).toHaveBeenCalledWith(house.id, expect.any(AbortSignal), 0, "open"));
    window.localStorage.clear();
  });
  it("passes the explicit house selector to the server on incident navigation", async () => {
    window.history.replaceState(null, "", `/?house=wrong&incident=${incident.id}`);
    const client = apiWith();
    vi.mocked(client.incident).mockRejectedValue(error(403));
    render(<App client={client} />);
    await screen.findByText("Нет доступа к этому дому");
    expect(client.incident).toHaveBeenCalledWith(incident.id, expect.any(AbortSignal), "wrong");
    expect(screen.queryByText(incident.description)).toBeNull();
  });
  it("keeps participant count distinct and handles unknown counts", async () => {
    window.history.replaceState(null, "", `/?incident=${incident.id}`);
    const client = apiWith([{ ...incident, participant_count: null, report_count: 4 }]);
    render(<App client={client} />);
    await screen.findByRole("heading", { name: "Что известно" });
    expect(screen.getByText("Сообщили").nextElementSibling?.textContent).toBe("Нет данных, 4 сообщения");
    expect(screen.queryByRole("button", { name: "Подготовить обращение" })).toBeNull();
  });
  it("does not offer report retry when the producer forbids it", async () => {
    const client = apiWith([]);
    vi.mocked(client.previewReport).mockRejectedValue(error(403));
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: "Сообщить о проблеме" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Опишите проблему" }), {
      target: { value: "Не работает лифт" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить описание" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("попробуйте ещё раз");
    expect((screen.getByRole("button", { name: "Проверить описание" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.queryByText("PRIVATE")).toBeNull();
  });
  it("keeps the described problem and reuses the idempotency key after an ambiguous failure", async () => {
    const client = apiWith([]);
    vi.mocked(client.submitReport).mockRejectedValueOnce(new Error("network"));
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: "Сообщить о проблеме" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Опишите проблему" }), {
      target: { value: "Не работает лифт" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить описание" }));
    // Перед отправкой виден адрес дома.
    expect(await screen.findByText(house.address)).toBeTruthy();
    const send = await screen.findByRole("button", { name: "Всё верно, отправить" });
    fireEvent.click(send);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Всё верно, отправить" }));
    await waitFor(() => expect(client.submitReport).toHaveBeenCalledTimes(2));
    expect(vi.mocked(client.submitReport).mock.calls[0][2]).toBe(
      vi.mocked(client.submitReport).mock.calls[1][2],
    );
    // Описание жителя остаётся: неудача отправки не теряет его слова.
    expect(vi.mocked(client.submitReport).mock.calls[1][1].description).toBe(
      "Не работает лифт",
    );
  });
});

describe("route card and appeal draft navigation", () => {
  const ref = `r_${"a".repeat(32)}`;
  function launched() {
    const client = apiWith();
    vi.mocked(client.notificationLaunch).mockResolvedValue({
      kind: "route_card",
      incident_id: null,
      house_id: house.id,
      route_outcome_id: outcome.id,
      work_attempt_id: null,
      stale: false,
    });
    return client;
  }

  it("an r_ launch link opens the route card, not the house board", async () => {
    window.history.replaceState(null, "", `/?test_start_param=${ref}`);
    const client = launched();
    render(<App client={client} />);
    await screen.findByText(actionCard.title);
    expect(client.routeOutcome).toHaveBeenCalledWith(
      outcome.id,
      expect.any(AbortSignal),
    );
    expect(client.incident).not.toHaveBeenCalled();
    // Адрес меняет эффект после отрисовки карточки — ждать, а не читать сразу.
    await waitFor(() => expect(window.location.search).toContain(`card=${outcome.id}`));
  });

  it("the card screen opens the appeal draft and returns to the card", async () => {
    window.history.replaceState(null, "", `/?card=${outcome.id}`);
    const client = apiWith();
    render(<App client={client} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Подготовить текст обращения" }),
    );
    await screen.findByRole("heading", { name: "Текст обращения" });
    expect(client.createAppealDraft).toHaveBeenCalledWith({
      house_id: house.id,
      route_outcome_id: outcome.id,
    });
    await waitFor(() => expect(window.location.search).toContain(`draft=${draft.id}`));
    // «Назад» возвращает туда, откуда пришли, — к карточке.
    fireEvent.click(screen.getByRole("button", { name: /Назад/ }));
    await screen.findByText(actionCard.title);
  });

  it("stale data does not lock the draft editor or copying (P6b live run)", async () => {
    window.history.replaceState(null, "", `/?draft=${draft.id}`);
    render(<App client={apiWith()} />);
    const area = await screen.findByRole("textbox", { name: "Обращение" });
    // Возврат из официального сервиса или минута на экране — «данные могли измениться».
    fireEvent(document, new Event("visibilitychange"));
    expect(await screen.findByText("Данные могли измениться.")).toBeTruthy();
    expect((area as HTMLTextAreaElement).disabled).toBe(false);
    expect(
      (screen.getByRole("button", { name: "Скопировать текст" }) as HTMLButtonElement).disabled,
    ).toBe(false);
    fireEvent.change(area, { target: { value: "Здравствуйте! Мой текст" } });
    expect((area as HTMLTextAreaElement).value).toBe("Здравствуйте! Мой текст");
  });

  it("says the route was refreshed when the directory changed", async () => {
    window.history.replaceState(null, "", `/?card=${outcome.id}`);
    const client = apiWith();
    vi.mocked(client.routeOutcome).mockResolvedValue({
      ...outcome,
      directory_changed: true,
    });
    render(<App client={client} />);
    expect(
      await screen.findByText("Сведения обновились — показываем актуальные."),
    ).toBeTruthy();
  });

  it.each([
    ["routes", `card=${outcome.id}`],
    ["appeals", `draft=${draft.id}`],
  ])("does not request a %s screen while the capability is off", async (flag, query) => {
    window.history.replaceState(null, "", `/?${query}`);
    const client = apiWith();
    const capabilities = await client.capabilities();
    vi.mocked(client.capabilities).mockResolvedValue({
      ...capabilities,
      features: { ...capabilities.features, [flag]: false },
    });
    render(<App client={client} />);
    await screen.findByText("Этот раздел сейчас выключен");
    expect(client.routeOutcome).not.toHaveBeenCalled();
    expect(client.appealDraft).not.toHaveBeenCalled();
  });

  it("a foreign or missing outcome is a plain not found", async () => {
    window.history.replaceState(null, "", `/?card=${outcome.id}`);
    const client = apiWith();
    vi.mocked(client.routeOutcome).mockRejectedValue(error(404));
    render(<App client={client} />);
    await screen.findByText("Карточка «Куда обратиться» не найдена");
    expect(screen.queryByText(actionCard.title)).toBeNull();
    expect(screen.queryByText("PRIVATE")).toBeNull();
  });
});

describe("launch refs from real MAX initData (D3 live finding)", () => {
  // В живой проверке кнопки «Открыть» и «Голосовать» из чата открывали доску:
  // мост MAX пропускал только `w_`/`r_`. Здесь ссылка идёт через настоящий
  // `start_param` из initData, а не через тестовый параметр адреса.
  it("a t_ chat post opens its problem", async () => {
    const ref = `t_${"c".repeat(32)}`;
    window.WebApp = { initData: `start_param=${ref}` };
    const client = apiWith();
    vi.mocked(client.notificationLaunch).mockResolvedValue({
      kind: "ticket",
      incident_id: incident.id,
      house_id: house.id,
      route_outcome_id: null,
      work_attempt_id: null,
      stale: false,
    });
    render(<App client={client} />);
    await screen.findByText(incident.description);
    expect(client.notificationLaunch).toHaveBeenCalledWith(ref, expect.any(AbortSignal));
    expect(client.incident).toHaveBeenCalledWith(incident.id, expect.any(AbortSignal), house.id);
    expect(client.incidents).not.toHaveBeenCalled();
  });

  it.each(["p", "n"])("a %s_ mailing link is resolved, not dropped", async (prefix) => {
    const ref = `${prefix}_${"d".repeat(32)}`;
    window.WebApp = { initData: `start_param=${ref}` };
    const client = apiWith();
    render(<App client={client} />);
    await waitFor(() =>
      expect(client.notificationLaunch).toHaveBeenCalledWith(ref, expect.any(AbortSignal)),
    );
  });
});
