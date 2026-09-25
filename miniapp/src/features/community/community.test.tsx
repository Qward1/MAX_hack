import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiProblem } from "../../shared/api/client";
import type { CommunityApi, HouseOverview, PollView } from "../../shared/api/community";
import {
  AnnouncementsScreen,
  type CommunityLinks,
  MyActivityScreen,
  MyHouseScreen,
  PollScreen,
  WorksScreen,
} from "./CommunityScreens";

const HOUSE = "00000000-0000-0000-0000-000000000101";

function links(): CommunityLinks {
  return {
    board: (house) => `/?house=${house ?? ""}`,
    view: (view, extra) => `/?view=${view}&house=${extra?.house ?? ""}&poll=${extra?.poll ?? ""}`,
    incident: (house, incident) => `/?house=${house}&incident=${incident}`,
    card: (house, card) => `/?house=${house}&card=${card}`,
    draft: (house, draft) => `/?house=${house}&draft=${draft}`,
    report: (house) => `/?house=${house}&report=1`,
    navigate: vi.fn(),
  };
}

function api(overrides: Partial<CommunityApi> = {}): CommunityApi {
  return {
    houseOverview: vi.fn(),
    completedWorks: vi.fn(),
    announcements: vi.fn(),
    poll: vi.fn(),
    vote: vi.fn(),
    myActivity: vi.fn(),
    setPreferences: vi.fn(),
    reception: vi.fn(),
    book: vi.fn(),
    cancelBooking: vi.fn(),
    ...overrides,
  };
}

const overview: HouseOverview = {
  house_id: HOUSE,
  name: "Дом",
  address: "Казань, Синтетическая улица, 1",
  entrance_count: 4,
  floor_count: 9,
  facts_updated_at: "2026-09-26T10:00:00Z",
  company: {
    name: "УК Первая",
    dispatcher_phone: "+7 843 000-00-02",
    phone: null,
    email: null,
    office_hours: "Пн–Пт 9:00–18:00",
    reception_hours: null,
    website: "https://uk.example.invalid",
    office_address: null,
    updated_at: "2026-09-26T10:00:00Z",
  },
  chat: { connected: true, reading_enabled: false },
  emergency: [
    {
      title: "При угрозе жизни и здоровью звоните 112",
      phone: "112",
      lines: ["ДомСигнал не заменяет экстренные службы."],
      source: { title: "Федеральный закон № 488-ФЗ", url: "http://publication.pravo.gov.ru/x", verified_at: "2026-09-20" },
    },
  ],
  channels: [
    {
      id: "pos_gosuslugi",
      label: "Госуслуги. Решаем вместе",
      channel_type: "official_web",
      url: "https://www.gosuslugi.ru/help/obratitsya_v_pos",
      phone: null,
      verification_status: "verified",
      source: { title: "480-ФЗ", url: null, verified_at: "2026-09-23" },
    },
  ],
  accident_steps: [
    { text: "При угрозе жизни и здоровью звоните по единому номеру 112.", basis: "directory", phone: "112",
      source: { title: "Федеральный закон № 488-ФЗ", url: null, verified_at: "2026-09-20" } },
    { text: "Аварийно-диспетчерская служба управляющей компании: +7 843 000-00-02 (по данным УК).",
      basis: "company", phone: "+7 843 000-00-02", source: null },
  ],
  reception_available: true,
};

describe("«Мой дом»", () => {
  it("подписывает сведения УК и показывает источник проверенных номеров", async () => {
    const nav = links();
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockResolvedValue(overview) })} houseId={HOUSE} links={nav} />);
    expect(await screen.findByText("Казань, Синтетическая улица, 1")).toBeTruthy();
    expect(screen.getByText(/Подъездов: 4 · Этажей: 9/)).toBeTruthy();
    expect(screen.getByText(/по данным УК, обновлено/)).toBeTruthy();
    expect(screen.getByText(/ДомСигнал эти сведения не проверяет/)).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "112" })[0].getAttribute("href")).toBe("tel:112");
    expect(screen.getAllByText(/проверено/).length).toBeGreaterThan(0);
    expect(screen.getByText("Подключён, бот отвечает на /report")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Записаться на приём" }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?view=reception&house=${HOUSE}&poll=`);
    expect(document.body.textContent?.toLowerCase()).not.toMatch(/тариф|норматив|капремонт/);
  });

  it("403 объясняет, как стать жителем, без тупика", async () => {
    const problem = new ApiProblem({ status: 403, type: "about:blank", code: "house_access_denied", title: "",
      detail: "", trace_id: "", retryable: false });
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockRejectedValue(problem) })} houseId={HOUSE} links={links()} />);
    expect(await screen.findByText("Раздел доступен жителям дома")).toBeTruthy();
    expect(screen.getByText(/кнопкой из вашего домового чата/)).toBeTruthy();
  });
});

describe("Объявления и опрос", () => {
  it("показывает подпись УК, опрос и переключатель рассылок", async () => {
    const setPreferences = vi.fn().mockResolvedValue({ broadcast_opt_out: true });
    const announcements = vi.fn().mockResolvedValue({
      items: [
        { id: "b1", kind: "announcement", topic: "outage", topic_label: "Отключение", title: "Отключение воды",
          body: "28 сентября с 10:00 до 14:00.", sender: "Сообщение от УК «УК Первая»", sent_at: "2026-09-27T07:00:00Z" },
        { id: "b2", kind: "poll", title: "Покраска подъезда", body: "", sender: "Сообщение от УК «УК Первая»",
          sent_at: "2026-09-27T08:00:00Z", poll: { poll_id: "p1", closes_at: "2026-09-30T08:00:00Z", closed: false, voters: 3, voted: false } },
      ],
      page: { limit: 20, offset: 0, total: 2 },
      broadcast_opt_out: false,
    });
    const nav = links();
    render(<AnnouncementsScreen api={api({ announcements, setPreferences })} houseId={HOUSE} links={nav} />);
    expect(await screen.findByText("Отключение воды")).toBeTruthy();
    expect(screen.getAllByText("Сообщение от УК «УК Первая»")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Голосовать" }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?view=poll&house=${HOUSE}&poll=p1`);
    fireEvent.click(screen.getByRole("button", { name: "Не получать рассылки" }));
    await waitFor(() => expect(setPreferences).toHaveBeenCalledWith(true));
    expect(await screen.findByText(/больше не придут в личные сообщения/)).toBeTruthy();
  });

  it("пустая лента — понятное состояние и путь назад", async () => {
    const announcements = vi.fn().mockResolvedValue({ items: [], page: { limit: 20, offset: 0, total: 0 }, broadcast_opt_out: false });
    render(<AnnouncementsScreen api={api({ announcements })} houseId={HOUSE} links={links()} />);
    expect(await screen.findByText("Объявлений пока нет")).toBeTruthy();
  });

  const poll: PollView = {
    id: "p1", broadcast_id: "b2", question: "Какой цвет стен выбрать?", multiple: false,
    closes_at: "2026-09-30T08:00:00Z", closed: false, voters: 1,
    options: [
      { id: "o1", position: 1, label: "Бежевый", votes: 1, share: 1 },
      { id: "o2", position: 2, label: "Светло-серый", votes: 0, share: 0 },
    ],
    my_choice: [], can_vote: true, reason: null, sender: "Сообщение от УК «УК Первая»",
    disclaimer: "Предварительный опрос. Не является решением общего собрания собственников.",
  };

  it("голос учитывается, итоги — числа и доли, подпись о собрании видна", async () => {
    const vote = vi.fn().mockResolvedValue({ ...poll, voters: 2, my_choice: ["o2"],
      options: [{ ...poll.options[0], votes: 1, share: 0.5 }, { ...poll.options[1], votes: 1, share: 0.5 }] });
    render(<PollScreen api={api({ poll: vi.fn().mockResolvedValue(poll), vote })} pollId="p1" houseId={HOUSE} links={links()} />);
    expect(await screen.findByText("Какой цвет стен выбрать?")).toBeTruthy();
    expect(screen.getByText(poll.disclaimer)).toBeTruthy();
    const submit = screen.getByRole("button", { name: "Проголосовать" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Светло-серый/));
    fireEvent.click(submit);
    await waitFor(() => expect(vote).toHaveBeenCalledWith("p1", ["o2"]));
    expect(await screen.findByText(/Голос учтён/)).toBeTruthy();
    expect(screen.getByText(/Проголосовали: 2/)).toBeTruthy();
    expect(screen.getAllByText(/50%/)).toHaveLength(2);
  });

  it("закрытый опрос не даёт голосовать и объясняет почему", async () => {
    render(<PollScreen api={api({ poll: vi.fn().mockResolvedValue({ ...poll, closed: true, can_vote: false, reason: "Опрос закрыт." }) })}
      pollId="p1" houseId={HOUSE} links={links()} />);
    expect(await screen.findByText("Опрос закрыт.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Проголосовать" })).toBeNull();
  });
});

describe("Выполненные работы и «Мои обращения»", () => {
  it("работы: период, итог проверки и переход к проблеме", async () => {
    const completedWorks = vi.fn().mockResolvedValue({
      days: 30,
      items: [{ attempt_id: "a1", incident_id: "i1", category: "elevator", category_title: "Проблема с лифтом",
        entrance: "2", public_description: "Заменён блок управления", reported_at: "2026-09-26T10:00:00Z",
        outcome: "returned", outcome_at: "2026-09-26T12:00:00Z" }],
      page: { limit: 20, offset: 0, total: 1 },
    });
    const nav = links();
    render(<WorksScreen api={api({ completedWorks })} houseId={HOUSE} links={nav} />);
    expect(await screen.findByText("Заменён блок управления")).toBeTruthy();
    expect(screen.getByText("Возвращено в работу")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "90 дней" }));
    await waitFor(() => expect(completedWorks).toHaveBeenLastCalledWith(HOUSE, 90, 0, expect.anything()));
    fireEvent.click(await screen.findByRole("button", { name: /^Открыть проблему/ }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?house=${HOUSE}&incident=i1`);
  });

  it("обращения: отметка жителя не выдаётся за регистрацию, пустое состояние ведёт к форме", async () => {
    const myActivity = vi.fn().mockResolvedValue({
      items: [{ kind: "appeal_draft", id: "d1", house_id: HOUSE, house_address: "Казань, 1",
        title: "Черновик обращения · Уличное освещение", status_label: "Вы отметили: «Я отправил»",
        occurred_at: "2026-09-26T10:00:00Z", appeal_draft_id: "d1", route_outcome_id: "r1",
        filed_at: "2026-09-26T11:00:00Z" }],
      page: { limit: 20, offset: 0, total: 1 },
    });
    const nav = links();
    const { unmount } = render(<MyActivityScreen api={api({ myActivity })} houseId={HOUSE} links={nav} />);
    expect(await screen.findByText(/ДомСигнал не подтверждает регистрацию во внешней системе/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Открыть черновик/ }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?house=${HOUSE}&draft=d1`);
    unmount();
    const empty = vi.fn().mockResolvedValue({ items: [], page: { limit: 20, offset: 0, total: 0 } });
    render(<MyActivityScreen api={api({ myActivity: empty })} houseId={HOUSE} links={nav} />);
    fireEvent.click(await screen.findByRole("button", { name: "Сообщить о проблеме" }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?house=${HOUSE}&report=1`);
  });
});
