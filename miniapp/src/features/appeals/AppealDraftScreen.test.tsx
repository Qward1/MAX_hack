import { MaxUI } from "@maxhub/max-ui";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AppealDraftView } from "../../shared/api/client";
import { apiWith, draft, error } from "../../test/fixtures";
import { AppealDraftScreen } from "./AppealDraftScreen";

/** Буфер обмена в jsdom отсутствует: подменяем только его, не весь navigator. */
function clipboard(writeText: () => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}
afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

function show(value: AppealDraftView = draft, client = apiWith()) {
  const onLoaded = vi.fn();
  render(
    <MaxUI>
      <AppealDraftScreen draft={value} client={client} onLoaded={onLoaded} />
    </MaxUI>,
  );
  return { client, onLoaded };
}

describe("appeal draft", () => {
  it("keeps the product order: copy, open the official service, mark filed", () => {
    show();
    const buttons = screen
      .getAllByRole("button")
      .map((node) => node.textContent)
      .filter((label) =>
        [
          "Скопировать текст",
          "Открыть официальный сервис",
          "Я отправил(а) обращение",
        ].includes(label ?? ""),
      );
    expect(buttons).toEqual([
      "Скопировать текст",
      "Открыть официальный сервис",
      "Я отправил(а) обращение",
    ]);
  });

  it("disables the transition without a verified link and shows the entry hint", () => {
    show();
    const button = screen.getByRole("button", {
      name: "Открыть официальный сервис",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.queryByRole("link", { name: /официальный сервис/ })).toBeNull();
    expect(screen.getByText(/Вход: Госуслуги/)).toBeTruthy();
    expect(screen.getByText(/ссылка входа ещё не заполнена/)).toBeTruthy();
  });

  it("marks the ai-assisted paragraph so the resident checks it", () => {
    show();
    expect(screen.getByText(/подготовлен с помощью ИИ/)).toBeTruthy();
  });

  it("a stale version keeps the resident input and offers the server text", async () => {
    const client = apiWith();
    vi.mocked(client.saveAppealDraft).mockRejectedValue(error(409));
    vi.mocked(client.appealDraft).mockResolvedValue({
      ...draft,
      version: 2,
      text: "Серверная версия черновика",
    });
    show(draft, client);
    const area = screen.getByRole("textbox", { name: "Обращение" });
    fireEvent.change(area, { target: { value: "Мой текст, который нельзя терять" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить правку" }));
    await screen.findByText("Черновик изменился. Ваш текст сохранён на экране.");
    expect((area as HTMLTextAreaElement).value).toBe("Мой текст, который нельзя терять");
    expect(screen.getByText("Серверная версия черновика")).toBeTruthy();
  });

  it("falls back to manual selection when the clipboard refuses", async () => {
    const write = vi.fn().mockRejectedValue(new Error("denied"));
    clipboard(write);
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    show();
    fireEvent.click(screen.getByRole("button", { name: "Скопировать текст" }));
    await screen.findByText("Выделите и скопируйте текст вручную.");
    expect(
      (screen.getByRole("textbox", { name: "Обращение" }) as HTMLTextAreaElement).value,
    ).toBe(draft.text);
    expect(errors).not.toHaveBeenCalled();
  });

  it("copies the current text when the clipboard is available", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    clipboard(write);
    show();
    fireEvent.click(screen.getByRole("button", { name: "Скопировать текст" }));
    await screen.findByText("Текст скопирован.");
    expect(write).toHaveBeenCalledWith(draft.text);
  });

  it("after the resident mark, editing stops and registration is not claimed", async () => {
    const filed: AppealDraftView = {
      ...draft,
      filed_at: "2026-09-20T11:00:00Z",
      filed_reference: "OBR-77",
      allowed_actions: [
        { code: "edit_draft", enabled: false, reason: "Вы уже отметили подачу этого обращения." },
        { code: "copy_draft", enabled: true, reason: null },
        { code: "open_official_channel", enabled: false, reason: "Ссылки пока нет." },
        { code: "mark_filed", enabled: false, reason: "Подача уже отмечена." },
      ],
    };
    show(filed);
    expect(
      screen.getByText(
        /Вы отметили, что отправили обращение\. ДомСигнал не подтверждает регистрацию во внешней системе\./,
      ),
    ).toBeTruthy();
    expect(
      (screen.getByRole("textbox", { name: "Обращение" }) as HTMLTextAreaElement).disabled,
    ).toBe(true);
    expect(screen.queryByRole("button", { name: "Сохранить правку" })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Я отправил(а) обращение" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("sends the optional reference the resident typed", async () => {
    const { client } = show();
    fireEvent.change(screen.getByLabelText(/Номер обращения/), {
      target: { value: " OBR-42 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Я отправил(а) обращение" }));
    await waitFor(() =>
      expect(client.markAppealFiled).toHaveBeenCalledWith(draft.id, "OBR-42"),
    );
  });
});
