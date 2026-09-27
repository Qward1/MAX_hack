import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Sheet } from "../shared/ui/ChoicePicker";
import { CompanyApply } from "./CompanyApply";
import adminHtml from "../../admin/index.html?raw";
import companyHtml from "../../company/index.html?raw";
import loginHtml from "../../login/index.html?raw";
import platformHtml from "../../platform-admin/index.html?raw";
import siteHtml from "../../site/index.html?raw";

describe("RA-01 заявка УК", () => {
  it("вступление ведёт к форме, подробности и политика — после формы", () => {
    const { container } = render(<CompanyApply />);
    const jump = screen.getByRole("link", { name: "Перейти к заявке" });
    expect(jump.getAttribute("href")).toBe("#company-application");
    const form = container.querySelector("#company-application") as HTMLElement;
    expect(form.querySelector("form")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Заявка управляющей компании" })).toBe(form);
    // Порядок телефона: вступление → форма → «Как проходит подключение» и политика данных.
    const steps = screen.getByText("Как проходит подключение");
    const privacy = screen.getByRole("link", { name: "Политика данных" });
    const after = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(after(jump, form)).toBe(true);
    expect(after(form, steps)).toBe(true);
    expect(after(form, privacy)).toBe(true);
  });
});

describe("RA-03 лист с закрытием в шапке", () => {
  it("значок «Закрыть» стоит в шапке и закрывает лист; без closeLabel его нет", () => {
    const onClose = vi.fn();
    const { unmount } = render(<Sheet title="Разделы кабинета" closeLabel="Закрыть" onClose={onClose}><a href="/a">Обзор</a></Sheet>);
    const close = screen.getByRole("button", { name: "Закрыть" });
    expect(close.closest(".ds-sheet-head")?.textContent).toContain("Разделы кабинета");
    expect(close.closest("dialog")?.className).toContain("has-close");
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    render(<Sheet title="Категория" onClose={vi.fn()}><button type="button">Готово</button></Sheet>);
    expect(screen.queryByRole("button", { name: "Закрыть" })).toBeNull();
  });
});

describe("RA-08 заголовки вкладок по задаче страницы", () => {
  const title = (html: string) => /<title>([^<]+)<\/title>/.exec(html)?.[1];
  it("у каждого entry свой заголовок", () => {
    const titles = {
      company: title(companyHtml),
      "platform-admin": title(platformHtml),
      admin: title(adminHtml),
      login: title(loginHtml),
      site: title(siteHtml),
    };
    expect(titles.company).toBe("Подключить УК · ДомСигнал");
    expect(titles["platform-admin"]).toBe("Управление платформой · ДомСигнал");
    expect(titles.admin).toBe("Кабинет УК · ДомСигнал");
    expect(new Set(Object.values(titles)).size).toBe(Object.keys(titles).length);
  });
});
