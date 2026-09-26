import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";
import { CheckAnswers, ConfirmDialog, StatePanel, Timeline } from "./semantic";

describe("кнопка", () => {
  it("выключенное действие — с видимой причиной, связанной с кнопкой, и не выполняется", () => {
    const run = vi.fn();
    render(
      <Button disabled reason="Ссылки на официальный сервис пока нет." onClick={run}>
        Открыть официальный сервис
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Открыть официальный сервис" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    const reason = document.getElementById(button.getAttribute("aria-describedby") ?? "");
    expect(reason?.textContent).toBe("Ссылки на официальный сервис пока нет.");
    fireEvent.click(button);
    expect(run).not.toHaveBeenCalled();
  });

  it("во время действия говорит «Отправляем…» и не принимает повторный клик", () => {
    const run = vi.fn();
    render(
      <Button variant="primary" loading loadingLabel="Отправляем…" onClick={run}>
        Отправить
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Отправляем…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(button);
    fireEvent.click(button);
    expect(run).not.toHaveBeenCalled();
  });
});

describe("состояния экрана", () => {
  it("ошибка называет, что делать, и даёт «Повторить»", () => {
    const retry = vi.fn();
    render(
      <StatePanel kind="error" title="Не удалось загрузить проблемы дома" detail="Проверьте интернет." action="Повторить" onAction={retry} />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Проверьте интернет.");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("пустое состояние — не тревога: без role=alert", () => {
    render(<StatePanel title="Объявлений пока нет" detail="Здесь появятся объявления." />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("загрузка объявляется через status и держит место каркасом", () => {
    const { container } = render(<StatePanel title="Загружаем" loading />);
    expect(screen.getByRole("status").textContent).toContain("Загружаем");
    expect(container.querySelector(".ds-skeleton")).toBeTruthy();
  });
});

describe("проверка ответов", () => {
  it("«Изменить» стоит у пункта и называет, что меняет", () => {
    const change = vi.fn();
    render(
      <CheckAnswers
        items={[
          { label: "Категория", value: "Лифт", change, changeLabel: "категорию" },
          { label: "Место", value: "Подъезд 2" },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Изменить категорию" }));
    expect(change).toHaveBeenCalledOnce();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});

describe("хронология", () => {
  it("после нескольких записей свёрнута и раскрывается кнопкой", () => {
    const events = Array.from({ length: 5 }, (_, i) => ({
      id: String(i),
      title: `Запись ${i}`,
      occurred_at: "2026-09-26T10:00:00Z",
    }));
    render(<Timeline events={events} label="сообщения" />);
    expect(screen.queryByText("Запись 4")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Показать все сообщения (5)" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByText("Запись 4")).toBeTruthy();
  });
});

describe("диалог подтверждения", () => {
  function Harness({ onConfirm }: { onConfirm: () => void }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Я отправил(а) обращение</button>
        {open && (
          <ConfirmDialog
            title="Отметить обращение как отправленное?"
            confirmLabel="Да, я отправил(а)"
            onConfirm={onConfirm}
            onCancel={() => setOpen(false)}
          />
        )}
      </>
    );
  }

  it("Esc закрывает без действия и возвращает фокус к кнопке", () => {
    const confirm = vi.fn();
    render(<Harness onConfirm={confirm} />);
    const trigger = screen.getByRole("button", { name: "Я отправил(а) обращение" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByText("Отметить обращение как отправленное?").closest("dialog")!;
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(screen.queryByText("Отметить обращение как отправленное?")).toBeNull();
    expect(confirm).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("подтверждение выполняет действие", () => {
    const confirm = vi.fn();
    render(<Harness onConfirm={confirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Я отправил(а) обращение" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, я отправил(а)" }));
    expect(confirm).toHaveBeenCalledOnce();
  });
});
