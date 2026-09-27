import { MaxUI } from "@maxhub/max-ui";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DomSignalApi, ReportPreview } from "../../shared/api/client";
import { apiWith, house, incident, preview } from "../../test/fixtures";
import { ReportFlow } from "./ReportFlow";

const candidate = {
  incident_id: incident.id,
  title: "Не работает лифт",
  category: "elevator",
  status: "open",
  created_at: "2026-09-19T09:00:00Z",
  report_count: 3,
  participant_count: 2,
  match_reason: "Та же категория, проблема открыта",
};

function show(client: DomSignalApi = apiWith()) {
  const onOpen = vi.fn();
  render(
    <MaxUI>
      <ReportFlow
        houseId={house.id}
        client={client}
        onOpen={onOpen}
        onCreated={vi.fn()}
      />
    </MaxUI>,
  );
  return { client, onOpen };
}

async function describeProblem(text = "у остановки не горят фонари") {
  fireEvent.change(screen.getByRole("textbox", { name: "Опишите проблему" }), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "Проверить описание" }));
  await screen.findByText("Проверьте, что мы поняли");
}

function withPreview(patch: Partial<ReportPreview["analysis"]>, duplicates = []) {
  const client = apiWith();
  vi.mocked(client.previewReport).mockResolvedValue({
    ...preview,
    analysis: { ...preview.analysis, ...patch },
    duplicates,
  });
  return client;
}

describe("report flow", () => {
  it("does not send anything while the resident is still describing", async () => {
    const { client } = show();
    await describeProblem();
    expect(client.submitReport).not.toHaveBeenCalled();
    expect(client.joinIncident).not.toHaveBeenCalled();
  });

  it("shows only the fields the backend actually returned", async () => {
    show(withPreview({ entrance: "2", floor: null, since: null }));
    await describeProblem();
    // Место, подъезд и этаж — одной строкой «Где», только из того, что вернул сервер.
    expect(screen.getByText("Где").nextElementSibling?.textContent).toBe(
      "Муниципальная территория, подъезд 2",
    );
    expect(screen.queryByText(/этаж/i)).toBeNull();
    expect(screen.queryByText("Наблюдается с")).toBeNull();
    expect(screen.queryByText("Признаки опасности")).toBeNull();
  });

  it("says out loud when the rules are not sure", async () => {
    show(withPreview({ confident: false }));
    await describeProblem();
    expect(screen.getByText(/Мы не уверены, что поняли всё правильно./)).toBeTruthy();
  });

  it("a found duplicate requires an explicit choice and sends nothing by itself", async () => {
    const client = withPreview({ category: "elevator" }, [candidate] as never);
    show(client);
    await describeProblem("опять лифт стоит");
    expect(screen.getByText("Похоже, об этом уже сообщали")).toBeTruthy();
    expect(screen.getByText(candidate.match_reason)).toBeTruthy();
    // Пока житель не выбрал — ни присоединения, ни новой проблемы.
    expect(client.joinIncident).not.toHaveBeenCalled();
    expect(client.submitReport).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /^Это та же проблема/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Нет, это другое" })).toBeTruthy();
  });

  it("joining an existing problem creates no second report", async () => {
    const client = withPreview({ category: "elevator" }, [candidate] as never);
    show(client);
    await describeProblem("опять лифт стоит");
    fireEvent.click(screen.getByRole("button", { name: /^Это та же проблема/ }));
    await screen.findByText("Вы присоединились к проблеме");
    expect(client.joinIncident).toHaveBeenCalledWith(candidate.incident_id, expect.any(String));
    expect(client.submitReport).not.toHaveBeenCalled();
  });

  it("choosing a different problem submits a new one", async () => {
    const client = withPreview({ category: "elevator" }, [candidate] as never);
    show(client);
    await describeProblem("опять лифт стоит");
    fireEvent.click(screen.getByRole("button", { name: "Нет, это другое" }));
    await waitFor(() => expect(client.submitReport).toHaveBeenCalled());
    expect(client.joinIncident).not.toHaveBeenCalled();
  });

  it("changing the category returns to the manual choice and sends it with the report", async () => {
    const { client } = show();
    await describeProblem();
    fireEvent.click(screen.getByRole("button", { name: /Изменить категорию/ }));
    // Возврат — сразу к выбору категории: фокус на нём, текущее значение видно.
    const picker = await screen.findByRole("button", { name: /Категория/ });
    await waitFor(() => expect(document.activeElement).toBe(picker));
    expect(picker.textContent).toContain("Определить по описанию");
    // Текст не пропал: повторно вводить не нужно.
    expect((screen.getByRole("textbox", { name: "Опишите проблему" }) as HTMLTextAreaElement).value).toBe(
      "у остановки не горят фонари",
    );
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole("radio", { name: "Отходы" }));
    fireEvent.click(screen.getByRole("button", { name: "Готово" }));
    expect(screen.getByRole("button", { name: /Категория/ }).textContent).toContain("Отходы");
    fireEvent.click(screen.getByRole("button", { name: "Проверить описание" }));
    fireEvent.click(await screen.findByRole("button", { name: "Всё верно, отправить" }));
    await waitFor(() => expect(client.submitReport).toHaveBeenCalled());
    expect(vi.mocked(client.submitReport).mock.calls[0][1]).toEqual({
      description: "у остановки не горят фонари",
      category: "waste",
    });
  });

  it("the result opens the appeal draft for an external route", async () => {
    const { client, onOpen } = show();
    await describeProblem();
    fireEvent.click(screen.getByRole("button", { name: "Всё верно, отправить" }));
    await screen.findByRole("heading", { name: "Сообщение сохранено" });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить текст обращения" }));
    await waitFor(() =>
      expect(onOpen).toHaveBeenCalledWith({ draft: expect.any(String), card: expect.any(String) }),
    );
    expect(client.createAppealDraft).toHaveBeenCalledWith({
      house_id: house.id,
      route_outcome_id: expect.any(String),
    });
  });

  it("reporting to the UK anyway does not claim the external route is closed", async () => {
    const { client } = show();
    await describeProblem();
    fireEvent.click(screen.getByRole("button", { name: "Всё верно, отправить" }));
    await screen.findByRole("heading", { name: "Сообщение сохранено" });
    fireEvent.click(screen.getByRole("button", { name: "Всё равно сообщить в УК" }));
    await screen.findByText(/Это не отменяет официальное обращение/);
    expect(vi.mocked(client.createReport).mock.calls[0][0].description).toBe(
      "у остановки не горят фонари",
    );
  });

  it("an unresolved route is explained honestly", async () => {
    const client = apiWith();
    vi.mocked(client.submitReport).mockResolvedValue({
      route_outcome_id: "00000000-0000-0000-0000-0000000005a1",
      decision: "needs_clarification",
      analysis: preview.analysis,
      action_card: preview.action_card,
      report: null,
    });
    show(client);
    await describeProblem();
    fireEvent.click(screen.getByRole("button", { name: "Всё верно, отправить" }));
    expect(
      await screen.findByText(
        "Ответственный пока не определён — разберёт диспетчер управляющей компании.",
      ),
    ).toBeTruthy();
  });

  it("keeps the text when the check fails and says what to do", async () => {
    const client = apiWith();
    vi.mocked(client.previewReport).mockRejectedValueOnce(new Error("offline"));
    show(client);
    fireEvent.change(screen.getByRole("textbox", { name: "Опишите проблему" }), {
      target: { value: "в подвале течёт труба" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить описание" }));
    expect(await screen.findByText(/Проверьте интернет и попробуйте ещё раз\. Текст сохранён\./)).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Опишите проблему" }) as HTMLTextAreaElement).value).toBe(
      "в подвале течёт труба",
    );
  });

  it("names a too short description at the field and sends nothing", () => {
    const { client } = show();
    const field = screen.getByRole("textbox", { name: "Опишите проблему" });
    fireEvent.change(field, { target: { value: "лифт" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить описание" }));
    const message = screen.getByText(/от 5 символов/);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(field.getAttribute("aria-describedby")).toContain(message.id);
    expect(client.previewReport).not.toHaveBeenCalled();
  });

  it("restores a draft kept by the app and reports every change back", () => {
    const onDraft = vi.fn();
    render(
      <ReportFlow
        houseId={house.id}
        client={apiWith()}
        draft={{ text: "с утра нет горячей воды", category: "water" }}
        onDraft={onDraft}
        onOpen={vi.fn()}
        onCreated={vi.fn()}
      />,
    );
    expect((screen.getByRole("textbox", { name: "Опишите проблему" }) as HTMLTextAreaElement).value).toBe(
      "с утра нет горячей воды",
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Опишите проблему" }), {
      target: { value: "с утра нет горячей воды во всём стояке" },
    });
    expect(onDraft).toHaveBeenLastCalledWith({ text: "с утра нет горячей воды во всём стояке", category: "water" });
  });

  it("offers the same and another problem as equal choices with nothing preselected", async () => {
    const client = withPreview({ category: "elevator" }, [candidate] as never);
    show(client);
    await describeProblem("опять лифт стоит");
    const same = screen.getByRole("button", { name: /^Это та же проблема/ });
    const other = screen.getByRole("button", { name: "Нет, это другое" });
    expect(same.className).toBe(other.className);
    expect(client.submitReport).not.toHaveBeenCalled();
    expect(client.joinIncident).not.toHaveBeenCalled();
  });
});
