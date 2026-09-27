import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HouseSwitch } from "./HouseSwitch";

const houses = [
  { id: "a", address: "Казань, ул. Пилотная, 7" },
  { id: "b", address: "Казань, ул. Тестовая, 1" },
  { id: "c", address: "Республика Татарстан, городской округ Казань, улица Академика Губкина, дом 127, корпус 3" },
];

function setup() {
  const onChange = vi.fn();
  render(<HouseSwitch houses={houses} value="a" onChange={onChange} />);
  const trigger = screen.getByRole("button", { name: "Дом Казань, ул. Пилотная, 7" });
  return { onChange, trigger };
}
const active = (list: HTMLElement) => document.getElementById(list.getAttribute("aria-activedescendant") ?? "")?.textContent;

describe("выбор дома", () => {
  it("список: текущий дом отмечен, фокус в списке, стрелки не меняют дом", () => {
    const { onChange, trigger } = setup();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const list = screen.getByRole("listbox", { name: "Дом" });
    expect(document.activeElement).toBe(list);
    expect(screen.getByRole("option", { selected: true }).textContent).toBe(houses[0].address);
    expect(active(list)).toBe(houses[0].address);
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(active(list)).toBe(houses[1].address);
    fireEvent.keyDown(list, { key: "End" });
    expect(active(list)).toBe(houses[2].address);
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(active(list)).toBe(houses[2].address);
    fireEvent.keyDown(list, { key: "Home" });
    fireEvent.keyDown(list, { key: "ArrowUp" });
    expect(active(list)).toBe(houses[0].address);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("Enter и пробел выбирают; фокус возвращается на кнопку", () => {
    const { onChange, trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("b");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "End" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: " " });
    expect(onChange).toHaveBeenLastCalledWith("c");
  });

  it("Esc и выбор текущего дома закрывают без смены", () => {
    const { onChange, trigger } = setup();
    fireEvent.click(trigger);
    fireEvent(screen.getByRole("dialog", { hidden: true }), new Event("cancel", { cancelable: true }));
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: houses[0].address }));
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("выбор касанием или мышью", () => {
    const { onChange, trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: houses[2].address }));
    expect(onChange).toHaveBeenCalledWith("c");
  });
});
