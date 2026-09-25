import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SignalClient, SignalView } from "../shared/api/signals";
import { SignalDetail } from "./SignalDetail";
import { countsLine, knownSignalActions, plural } from "./signalPresentation";

const route: SignalView["action_card"]["route"] = {
  route_type: "emergency_service",
  organization_id: null,
  organization_name: null,
  channels: [
    {
      id: "emergency_112",
      channel_type: "phone" as const,
      label: "Единый номер вызова экстренных оперативных служб",
      phone: "112",
      verification_status: "verified" as const,
      verified_at: "2026-09-20",
      source_title: "Федеральный закон № 488-ФЗ",
      routes_to_competent_authority: true,
      stale: false,
      facts: [],
    },
  ],
  basis: {
    rule_id: "federal.gas_smell.emergency",
    text: "Запах газа — повод вызвать экстренные службы.",
    source_title: "Федеральный закон № 488-ФЗ",
    verified_at: "2026-09-20",
    verification_status: "verified" as const,
  },
  directory_version: "_federal@1",
  automatic_integration: false,
  can_create_ticket: false,
  can_prepare_appeal: false,
  requires_operator_choice: false,
  match: "rule" as const,
  stale: false,
  hidden_unverified_channels: 0,
};

function view(overrides: Partial<SignalView> = {}): SignalView {
  return {
    id: "signal-1",
    house_id: "house-1",
    house_address: "Казань, Тестовая, 1",
    subtype: "other.unspecified",
    subtype_label: "Проблема",
    object_label: "запах газа",
    category: "other",
    strength: "critical",
    strength_reason:
      "Правила ДомСигнала нашли признак опасности в сообщении жителя.",
    status: "new",
    report_count: 1,
    author_count: 1,
    first_seen_at: "2026-09-23T10:00:00Z",
    last_seen_at: "2026-09-23T10:00:00Z",
    first_quote: {
      author: "Житель A",
      sent_at: "2026-09-23T10:00:00Z",
      text: "Пахнет газом",
    },
    place: { entrance: { value: "3", quote: "в третьем подъезде" } },
    route_type: "emergency_service",
    route_source: "router",
    requires_operator_choice: false,
    danger_kinds: ["gas"],
    is_demo: false,
    version: 3,
    territory: { scope: "unknown", label: "Территория не определена" },
    quotes: [
      {
        author: "Житель A",
        sent_at: "2026-09-23T10:00:00Z",
        text: "Пахнет газом",
      },
    ],
    danger: {
      kinds: ["gas"],
      labels: ["запах газа"],
      sources: ["rules"],
      evidence: [
        {
          kind: "gas",
          label: "запах газа",
          source: "rules",
          text: "Пахнет газом",
          author: "Житель A",
          sent_at: "2026-09-23T10:00:00Z",
        },
      ],
      preliminary: true,
      displaced: false,
      downgraded: false,
      evidence_unverified: false,
    },
    action_card: {
      route,
      audience: "operator",
      source: "chat",
      title: "Похоже на ситуацию для экстренных служб",
      explanation: "Такие сообщения адресуются экстренным службам.",
      safety: {
        title: "При угрозе жизни и здоровью звоните 112",
        lines: ["ДомСигнал не заменяет экстренные службы."],
        phone: "112",
        steps: [],
        source_title: "Федеральный закон № 488-ФЗ",
        verified_at: "2026-09-20",
      },
      facts: [],
      actions: [
        {
          type: "call_phone",
          label: "Позвонить 112",
          enabled: true,
          phone: "112",
        },
        {
          type: "route_external",
          label: "Отметить внешний маршрут",
          enabled: true,
        },
      ],
      generated_by: "rules",
    },
    route_choices: [],
    join_candidates: [],
    ticket_draft: {
      category: "other",
      description: "Из домового чата: проблема. Сообщений: 1, жителей: 1.",
    },
    allowed_actions: [
      { code: "route-external", enabled: true },
      { code: "dismiss", enabled: true },
      { code: "create-ticket", enabled: true },
      {
        code: "join",
        enabled: false,
        reason: "Открытых проблем той же категории нет.",
      },
      // Неизвестная команда не рисуется.
      { code: "teleport" as never, enabled: true },
    ],
    events: [
      {
        kind: "preliminary_critical",
        label: "Правила нашли признак опасности",
        at: "2026-09-23T10:00:00Z",
      },
    ],
    ...overrides,
  };
}

function setup(initial: SignalView = view()) {
  const client = {
    signalDetail: vi.fn().mockResolvedValue(initial),
    decide: vi.fn(),
  } as unknown as SignalClient;
  const openTicket = vi.fn();
  render(
    <SignalDetail
      client={client}
      id="signal-1"
      backHref="/admin/?section=signals"
      navigate={vi.fn()}
      openTicket={openTicket}
    />,
  );
  return { client, openTicket };
}

describe("P5 signal detail", () => {
  it("puts danger and safety first, then the decision, what/where, quotes, strength, route, history", async () => {
    setup();
    await screen.findByRole("heading", { name: "Опасность: запах газа" });
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent ?? "");
    expect(headings).toEqual([
      "Опасность: запах газа",
      // Решение видно без прокрутки: сразу после опасности.
      "Действия по сигналу",
      "Что, где и когда",
      "Слова жителей",
      "Почему критический",
      "Похоже на ситуацию для экстренных служб",
      "История решения",
    ]);
    expect(
      screen.getByRole("link", { name: "Позвонить 112" }).getAttribute("href"),
    ).toBe("tel:112");
    expect(screen.getByText(/Переписку ещё разбирают/)).toBeTruthy();
  });

  it("renders only known server actions; a disabled one explains why", async () => {
    setup();
    const panel = await screen.findByRole("region", {
      name: "Действия по сигналу",
    });
    const buttons = within(panel)
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(buttons).toEqual([
      "Отметить внешний маршрут",
      "Закрыть",
      "Создать заявку",
      "Присоединить к проблеме",
    ]);
    const join = within(panel).getByRole("button", {
      name: "Присоединить к проблеме",
    });
    expect((join as HTMLButtonElement).disabled).toBe(true);
    const reason = join.getAttribute("aria-describedby");
    expect(reason && document.getElementById(reason)?.textContent).toBe(
      "Открытых проблем той же категории нет.",
    );
  });

  it("shows what goes into the ticket before sending and sends the version", async () => {
    const { client } = setup();
    fireEvent.click(
      await screen.findByRole("button", { name: "Создать заявку" }),
    );
    const text = screen.getByRole("textbox", {
      name: "Описание заявки",
    }) as HTMLTextAreaElement;
    expect(text.value).toBe(
      "Из домового чата: проблема. Сообщений: 1, жителей: 1.",
    );
    expect(
      (screen.getByRole("combobox", { name: "Категория" }) as HTMLSelectElement)
        .value,
    ).toBe("other");
    fireEvent.change(text, {
      target: { value: "Запах газа в третьем подъезде" },
    });
    vi.mocked(client.decide).mockResolvedValue({
      signal: view({ status: "converted", allowed_actions: [] }),
      replayed: false,
      effect_version: 4,
    });
    vi.mocked(client.signalDetail).mockResolvedValue(
      view({
        status: "converted",
        allowed_actions: [],
        linked: {
          incident_id: "i-1",
          title: "Другая проблема дома",
          ticket_id: "t-1",
          ticket_number: "T-9",
        },
      }),
    );
    const form = screen.getByRole("form", { name: "Создать заявку" });
    fireEvent.click(
      within(form).getByRole("button", { name: "Создать заявку" }),
    );
    await waitFor(() => expect(client.decide).toHaveBeenCalledOnce());
    const [id, code, payload] = vi.mocked(client.decide).mock.calls[0];
    expect([id, code]).toEqual(["signal-1", "create-ticket"]);
    expect(payload).toEqual({
      expected_version: 3,
      category: "other",
      description: "Запах газа в третьем подъезде",
    });
    expect(await screen.findByText(/Заявка T-9 создана/)).toBeTruthy();
  });

  it("does not close a signal without a reason", async () => {
    const { client } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));
    const form = screen.getByRole("form", { name: "Закрыть" });
    const submit = within(form).getByRole("button", {
      name: "Закрыть сигнал",
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(form).getByRole("combobox", { name: "Причина" }), {
      target: { value: "duplicate" },
    });
    expect(submit.disabled).toBe(false);
    vi.mocked(client.decide).mockResolvedValue({
      signal: view({ status: "dismissed", allowed_actions: [] }),
      replayed: false,
      effect_version: 4,
    });
    fireEvent.click(submit);
    await waitFor(() => expect(client.decide).toHaveBeenCalledOnce());
    expect(vi.mocked(client.decide).mock.calls[0][2]).toEqual({
      expected_version: 3,
      reason: "duplicate",
    });
  });

  it("route choice offers only the server's choices and marks unverified data", async () => {
    setup(
      view({
        strength: "weak",
        danger: null,
        danger_kinds: [],
        route_type: "unknown",
        route_choices: ["uk_internal", "municipality"],
        action_card: {
          ...view().action_card,
          safety: null,
          route: {
            ...route,
            route_type: "unknown",
            basis: null,
            channels: [],
            stale: true,
          },
          title: "Не удалось надёжно определить ответственную организацию",
          actions: [
            {
              type: "operator_review",
              label: "Определить маршрут вручную",
              enabled: true,
            },
          ],
        },
        allowed_actions: [
          { code: "choose-route", enabled: true },
          {
            code: "route-external",
            enabled: false,
            reason: "Сначала выберите маршрут.",
          },
          { code: "dismiss", enabled: true },
        ],
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Выбрать маршрут" }),
    );
    const options = within(screen.getByRole("combobox", { name: "Маршрут" }))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual([
      "Выберите маршрут",
      "Управляющая компания дома",
      "Муниципалитет",
    ]);
    expect(screen.getByText("Сведения требуют сверки.")).toBeTruthy();
    expect(screen.getByText(/Правила в справочнике нет/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Опасность/ })).toBeNull();
  });

  it("a decided signal shows who decided and links to the ticket", async () => {
    const { openTicket } = setup(
      view({
        status: "converted",
        allowed_actions: [],
        decision: {
          status: "converted",
          decided_by: "Оператор Анна",
          decided_at: "2026-09-23T10:05:00Z",
        },
        linked: {
          incident_id: "i-1",
          title: "Проблема с лифтом",
          ticket_id: "t-1",
          ticket_number: "T-3",
        },
      }),
    );
    expect(await screen.findByText("Оператор Анна")).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Открыть заявку T-3" }));
    expect(openTicket).toHaveBeenCalledWith("t-1");
  });
});

describe("P5 signal presentation", () => {
  it("ignores unknown and malformed commands", () => {
    expect(
      knownSignalActions([
        { code: "dismiss", enabled: true },
        { code: "dismiss", enabled: false },
        { code: "fly", enabled: true },
        { code: "join" },
        null,
      ]),
    ).toEqual([{ code: "dismiss", enabled: true, reason: null }]);
    expect(knownSignalActions("nope")).toEqual([]);
  });
  it("counts in Russian", () => {
    expect(plural(1, "реплика", "реплики", "реплик")).toBe("реплика");
    expect(plural(3, "реплика", "реплики", "реплик")).toBe("реплики");
    expect(plural(11, "реплика", "реплики", "реплик")).toBe("реплик");
    expect(plural(21, "реплика", "реплики", "реплик")).toBe("реплика");
    expect(plural(104, "реплика", "реплики", "реплик")).toBe("реплики");
    expect(countsLine(7, 5, "2026-09-23T10:00:00Z")).toMatch(
      /^7 реплик · 5 жителей · последняя .+ МСК$/,
    );
  });
});
