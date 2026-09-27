import { MaxUI } from "@maxhub/max-ui";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionCard } from "../../shared/api/client";
import { actionCard } from "../../test/fixtures";
import { RouteCard } from "./RouteCard";

const safety = {
  title: "Похоже на запах газа",
  lines: ["Не пользуйтесь электроприборами.", "Проветрите помещение."],
  phone: "112",
  steps: [
    {
      text: "Выйдите из помещения и позвоните в экстренные службы.",
      source_title: "Памятка МЧС",
      source_url: "https://example.org/safety",
    },
  ],
  source_title: "Памятка МЧС",
  source_url: "https://example.org/safety",
  verified_at: "2026-09-20",
};

function card(patch: Partial<ActionCard> = {}): ActionCard {
  return { ...actionCard, ...patch };
}
function show(value: ActionCard, handlers = {}) {
  return render(
    <MaxUI>
      <RouteCard card={value} handlers={handlers} />
    </MaxUI>,
  );
}

describe("route card", () => {
  it("keeps the block order and puts safety above the route title", () => {
    const { container } = show(card({ safety }));
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (node) => node.textContent,
    );
    expect(headings).toEqual([
      safety.title,
      actionCard.title,
      "Основание",
      "Что известно об официальном сервисе",
      "Что можно сделать",
    ]);
    // Телефон экстренных служб — настоящая ссылка, а не подпись.
    expect(
      screen.getByRole("link", { name: /Позвонить 112/ }).getAttribute("href"),
    ).toBe("tel:112");
    expect(screen.getAllByText(/Проверено: 20 сентября 2026/)).toHaveLength(2);
  });

  it("shows a disabled transition with its reason and without any link", () => {
    show(card());
    const button = screen.getByRole("button", {
      name: "Перейти: Госуслуги. Решаем вместе",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    const described = button.getAttribute("aria-describedby");
    expect(described).toBeTruthy();
    expect(document.getElementById(described!)?.textContent).toContain(
      "ссылка входа ещё не заполнена",
    );
    expect(
      screen.queryByRole("link", { name: /Госуслуги. Решаем вместе/ }),
    ).toBeNull();
  });

  it("a disabled action does not run its handler", () => {
    const run = vi.fn();
    show(
      card({
        actions: [
          {
            type: "prepare_appeal",
            label: "Подготовить текст обращения",
            enabled: false,
            reason: "Проверенного канала для этого маршрута пока нет.",
            url: null,
            phone: null,
          },
        ],
      }),
      { prepare_appeal: run },
    );
    fireEvent.click(screen.getByRole("button", { name: "Подготовить текст обращения" }));
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByText(/Проверенного канала/)).toBeTruthy();
  });

  it("ignores an unknown action type and keeps the rest in backend order", () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    show(
      card({
        actions: [
          {
            type: "teleport_to_authority",
            label: "PRIVATE FUTURE ACTION",
            enabled: true,
            reason: null,
            url: null,
            phone: null,
          },
          actionCard.actions![1],
          actionCard.actions![2],
        ] as ActionCard["actions"],
      }),
      { prepare_appeal: vi.fn(), report_to_uk_anyway: vi.fn() },
    );
    expect(screen.queryByText("PRIVATE FUTURE ACTION")).toBeNull();
    expect(warning.mock.calls.flat().join()).not.toContain("teleport_to_authority");
    const buttons = screen
      .getAllByRole("button")
      .map((node) => node.textContent);
    expect(buttons).toEqual(["Подготовить текст обращения", "Всё равно сообщить в УК"]);
  });

  it("never renders operator-audience actions for a resident", () => {
    show(
      card({
        actions: [
          {
            type: "operator_review",
            label: "Определить маршрут вручную",
            enabled: true,
            reason: null,
            url: null,
            phone: null,
          },
          {
            type: "route_external",
            label: "Отметить внешний маршрут",
            enabled: true,
            reason: null,
            url: null,
            phone: null,
          },
          {
            type: "not_a_problem",
            label: "Отметить, что проблемы нет",
            enabled: true,
            reason: null,
            url: null,
            phone: null,
          },
        ],
      }),
    );
    for (const label of [
      "Определить маршрут вручную",
      "Отметить внешний маршрут",
      "Отметить, что проблемы нет",
    ])
      expect(screen.queryByText(label)).toBeNull();
    expect(screen.getByText("Доступных здесь шагов пока нет.")).toBeTruthy();
  });

  it("marks an unverified basis instead of staying silent", () => {
    show(
      card({
        route: {
          ...actionCard.route,
          stale: true,
          basis: { ...actionCard.route.basis!, verification_status: "demo" },
        },
      }),
    );
    // RA-07: названо, что не сверено, — кто отвечает, по полю basis.verification_status.
    expect(
      screen.getByText("Кто отвечает — указано предварительно: основание в справочнике ДомСигнала ещё не сверено."),
    ).toBeTruthy();
    expect(screen.queryByText("Сведения требуют сверки.")).toBeNull();
  });

  it("names the stale official service and stays silent when all is verified", () => {
    const channel = { ...actionCard.route.channels![0], stale: true, verified_at: "2026-01-10" };
    const view = show(card({ route: { ...actionCard.route, stale: true, channels: [channel] } }));
    expect(
      screen.getByText("Сведения о сервисе «Госуслуги. Решаем вместе» сверяли 10 января 2026 г. — нужна повторная сверка."),
    ).toBeTruthy();
    // Устарел только канал — основание не объявлено устаревшим.
    expect(screen.queryByText(/Основание, кто отвечает/)).toBeNull();
    view.unmount();
    show(card());
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("names an old basis when the route is stale without stale services", () => {
    show(card({ route: { ...actionCard.route, stale: true, basis: { ...actionCard.route.basis!, verified_at: "2026-01-10" } } }));
    expect(screen.getByText("Основание, кто отвечает, сверяли 10 января 2026 г. — нужна повторная сверка.")).toBeTruthy();
  });

  it("opens a verified official channel as a real link", () => {
    show(
      card({
        actions: [
          {
            type: "open_official_channel",
            label: "Перейти: официальный сервис",
            enabled: true,
            reason: null,
            url: "https://example.org/appeal",
            phone: null,
          },
        ],
      }),
    );
    const link = screen.getByRole("link", { name: /Перейти: официальный сервис/ });
    expect(link.getAttribute("href")).toBe("https://example.org/appeal");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });
});
