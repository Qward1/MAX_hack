import { describe, expect, it } from "vitest";
import { countLabel, formatDay, formatStaffTime, formatStaffWhen, formatWhen, pluralize } from "./format";

const NEIGHBOURS = ["сосед", "соседа", "соседей"] as const;

describe("числительные", () => {
  it.each([
    [0, "0 соседей"],
    [1, "1 сосед"],
    [2, "2 соседа"],
    [4, "4 соседа"],
    [5, "5 соседей"],
    [11, "11 соседей"],
    [12, "12 соседей"],
    [14, "14 соседей"],
    [21, "21 сосед"],
    [22, "22 соседа"],
    [101, "101 сосед"],
    [111, "111 соседей"],
  ])("%i → «%s»", (count, text) => {
    expect(countLabel(count, NEIGHBOURS)).toBe(text);
  });
  it("возвращает только форму слова", () => {
    expect(pluralize(3, ["заявка", "заявки", "заявок"])).toBe("заявки");
  });
});

describe("даты для жителя", () => {
  const now = new Date(2026, 8, 26, 15, 0);
  it("сегодня и вчера — словами, со временем", () => {
    expect(formatWhen(new Date(2026, 8, 26, 14, 5).toISOString(), now)).toBe("сегодня, 14:05");
    expect(formatWhen(new Date(2026, 8, 25, 9, 30).toISOString(), now)).toBe("вчера, 09:30");
  });
  it("дальше — день и месяц словами", () => {
    expect(formatWhen(new Date(2026, 8, 12, 10, 15).toISOString(), now)).toBe("12 сентября, 10:15");
  });
  it("прошлый год — с годом и без времени", () => {
    expect(formatWhen(new Date(2025, 2, 3, 10, 0).toISOString(), now)).toMatch(/^3 марта 2025/);
  });
  it("нет даты или она неверна — ничего не выдумывает", () => {
    expect(formatWhen(null)).toBeNull();
    expect(formatWhen("не дата")).toBeNull();
  });
});

describe("даты для сотрудника — по Москве и с «МСК»", () => {
  it("точное время", () => {
    expect(formatStaffTime("2026-09-26T11:05:00Z")).toBe("26.09.2026, 14:05 МСК");
  });
  it("в списках — относительно, но по Москве", () => {
    const now = new Date("2026-09-26T12:00:00Z");
    expect(formatStaffWhen("2026-09-26T11:05:00Z", now)).toBe("сегодня, 14:05 МСК");
    expect(formatStaffWhen("2026-09-25T06:30:00Z", now)).toBe("вчера, 09:30 МСК");
    // 22:30 UTC — это уже следующий день в Москве.
    expect(formatStaffWhen("2026-09-25T22:30:00Z", now)).toBe("сегодня, 01:30 МСК");
  });
});

describe("день проверки справочника", () => {
  it("только день, без выдуманного времени", () => {
    expect(formatDay("2026-09-20")).toBe("20 сентября 2026 г.");
    expect(formatDay("2026-09-20T23:59:00Z")).toBe("20 сентября 2026 г.");
    expect(formatDay(undefined)).toBeNull();
  });
});
