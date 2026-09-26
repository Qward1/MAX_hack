import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { PlatformHouses } from "./PlatformApp";

afterEach(() => vi.restoreAllMocks());

const packs: Schema["RegionPackView"][] = [
  { region_code: "RU-MOW", name: "Москва", timezone: "Europe/Moscow", version: "1", municipalities: [{ code: "moscow", name: "Москва" }] },
  { region_code: "RU-TA", name: "Республика Татарстан", timezone: "Europe/Moscow", version: "2", municipalities: [{ code: "kazan", name: "Казань" }] },
];

describe("D4: регион дома у платформы", () => {
  it("дом без профиля помечен «Регион не задан»; регион задаётся из справочника с основанием", async () => {
    const houses: Schema["PlatformHouseView"][] = [
      { id: "h1", address: "Москва, ул. Проверочная, 1", name: "h1", region_code: null },
      { id: "h2", address: "Казань, ул. Пилотная, 7", name: "h2", region_code: "RU-TA", municipality_code: "kazan", territory_policy: "mixed" },
    ];
    const request = vi.spyOn(adminClient, "request").mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.startsWith("/api/v1/platform/houses?")) return houses;
      if (path === "/api/v1/platform/open-houses") return [];
      if (path === "/api/v1/platform/region-packs") return packs;
      if (init?.method === "POST") return { ...houses[0], region_code: "RU-MOW", municipality_code: "moscow", territory_policy: "mixed" };
      throw new Error(`unexpected ${path}`);
    });
    render(<PlatformHouses />);
    const row = (await screen.findByText("Москва, ул. Проверочная, 1")).closest("li") as HTMLElement;
    expect(within(row).getByText("Регион не задан")).toBeTruthy();
    const kazan = screen.getByText("Казань, ул. Пилотная, 7").closest("li") as HTMLElement;
    expect(within(kazan).queryByText("Регион не задан")).toBeNull();
    expect(within(kazan).getByText("RU-TA / kazan")).toBeTruthy();

    fireEvent.click(within(row).getByRole("button", { name: "Задать регион" }));
    const save = within(row).getByRole("button", { name: "Сохранить регион" });
    expect((save as HTMLButtonElement).disabled).toBe(true); // без региона сохранить нельзя
    await waitFor(() => expect(within(row).getAllByRole("option").length).toBeGreaterThan(2));
    fireEvent.change(within(row).getByLabelText("Регион"), { target: { value: "RU-MOW" } });
    fireEvent.change(within(row).getByLabelText("Основание"), { target: { value: "Адрес в Москве" } });
    fireEvent.click(within(row).getByRole("button", { name: "Сохранить регион" }));
    await waitFor(() => expect(request.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(true));
    const [path, init] = request.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "POST") as [string, RequestInit];
    expect(path).toBe("/api/v1/platform/houses/h1/region");
    expect(JSON.parse(String(init.body))).toEqual({
      reason: "Адрес в Москве", region_code: "RU-MOW", municipality_code: "moscow", territory_policy: "mixed",
    });
  });
});
