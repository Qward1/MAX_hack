import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import schema from "../api/schema.ts?raw";
import { StatusTag } from "./semantic";
import {
  residentIncidentStatus,
  residentTicketStatus,
  signalStatus,
  signalStrength,
  staffTicketStatus,
  statusOf,
  TONE_MARK,
} from "./status";

/** Значения перечислений берутся из сгенерированной схемы API, а не из памяти. */
function enumValues(name: string): string[] {
  const union = new RegExp(`\\n\\s+${name}: ((?:"[a-z_]+"(?: \\| )?)+);`).exec(schema)?.[1] ?? "";
  return [...union.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
}

describe("словарь статусов", () => {
  it.each([
    ["IncidentStatus", residentIncidentStatus],
    ["TicketStatus", residentTicketStatus],
    ["TicketStatus", staffTicketStatus],
  ] as const)("покрывает все значения %s из API", (name, dictionary) => {
    const values = enumValues(name);
    expect(values.length).toBeGreaterThan(0);
    for (const value of values) expect(Object.hasOwn(dictionary, value), value).toBe(true);
  });

  it("покрывает статусы и силу сигнала", () => {
    for (const value of ["new", "in_review", "converted", "routed_external", "dismissed"])
      expect(Object.hasOwn(signalStatus, value)).toBe(true);
    for (const value of ["critical", "strong", "medium", "weak"]) expect(Object.hasOwn(signalStrength, value)).toBe(true);
    // Опасное отличается не только цветом: и подписью, и тоном «опасность».
    expect(signalStrength.critical.tone).toBe("danger");
  });

  it("неизвестное значение — нейтральное «Состояние обновилось» без содержимого сервера", () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    const entry = statusOf(residentTicketStatus, "private-future-state");
    expect(entry.label).toBe("Состояние обновилось");
    expect(entry.tone).toBe("neutral");
    expect(warning.mock.calls.flat().join()).not.toContain("private-future-state");
  });

  it("тег передаёт статус текстом и знаком, а не только цветом, и не кликабелен", () => {
    const { container } = render(<StatusTag entry={residentTicketStatus.verification_pending} />);
    const tag = screen.getByText("Ждёт проверки жителями");
    expect(tag.className).toContain("ds-tone-warning");
    expect(container.textContent).toContain(TONE_MARK.warning);
    expect(container.querySelector("button, a, [role=button], [tabindex]")).toBeNull();
  });

  it("у жителя и сотрудника смысл статуса один, различаются только слова", () => {
    expect(Object.keys(residentTicketStatus).sort()).toEqual(Object.keys(staffTicketStatus).sort());
  });
});
