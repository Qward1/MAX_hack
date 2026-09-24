import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { NoticeAgain, OpenAccessSwitch } from "./CompanyPages";

const house = {
  house_id: "house-1",
  management_id: "management-1",
  address: "Казань, Синтетическая улица, 1",
  open_resident_access: false,
} as unknown as Schema["CompanyHouseView"];

afterEach(() => vi.restoreAllMocks());

describe("OpenAccessSwitch (D1): открытый доступ к дому", () => {
  it("включает только после подтверждения с текстом о последствиях", async () => {
    const request = vi.spyOn(adminClient, "request").mockResolvedValue({
      house_id: "house-1",
      open_resident_access: true,
      open_access_changed_at: null,
      ended_memberships: 0,
    });
    const refresh = vi.fn();
    render(<OpenAccessSwitch base="/api/v1/companies/c1" house={house} refresh={refresh} />);
    expect(screen.getByText("Открытый доступ:")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Включить открытый доступ" }));
    expect(request).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Любой пользователь MAX сможет выбрать этот дом, сообщать о проблемах и видеть доску дома.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить: включить" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [path, init] = request.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/companies/c1/houses/house-1/open-access");
    expect(JSON.parse(String(init.body))).toEqual({ enabled: true, confirm: true });
  });

  it("предупреждает при выключении, что история остаётся у УК", () => {
    render(
      <OpenAccessSwitch
        base="/api/v1/companies/c1"
        house={{ ...house, open_resident_access: true }}
        refresh={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Выключить открытый доступ" }));
    expect(screen.getByText(/сразу потеряют доступ. Их заявки и история останутся у вас/)).toBeTruthy();
  });

  it("показывает отказ сервера человеческими словами", async () => {
    vi.spyOn(adminClient, "request").mockRejectedValue(new Error("Дом не найден"));
    render(<OpenAccessSwitch base="/api/v1/companies/c1" house={house} refresh={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Включить открытый доступ" }));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить: включить" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Дом не найден")).toBeTruthy();
  });

  it("не содержит пометок «тест» и «демо»", () => {
    const { container } = render(
      <OpenAccessSwitch base="/api/v1/companies/c1" house={house} refresh={() => undefined} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Включить открытый доступ" }));
    expect(container.textContent?.toLowerCase()).not.toMatch(/тест|демо/);
  });
});

describe("NoticeAgain (D1): сообщение с кнопкой ещё раз", () => {
  it("ставит сообщение и сообщает о повторе в пределах 10 минут", async () => {
    const request = vi
      .spyOn(adminClient, "request")
      .mockResolvedValueOnce({ binding_id: "binding-1", queued: true })
      .mockResolvedValueOnce({ binding_id: "binding-1", queued: false });
    render(<NoticeAgain binding="binding-1" />);
    const button = screen.getByRole("button", { name: "Отправить сообщение с кнопкой ещё раз" });
    fireEvent.click(button);
    expect(await screen.findByText(/поставлено в очередь отправки в чат/)).toBeTruthy();
    fireEvent.click(button);
    expect(await screen.findByText(/уже отправлялось в последние 10 минут/)).toBeTruthy();
    expect(request.mock.calls[0][0]).toBe("/api/v1/chat-bindings/binding-1/notice");
  });
});
