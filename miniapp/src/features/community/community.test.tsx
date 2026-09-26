import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiProblem } from "../../shared/api/client";
import type { CommunityApi, CouncilView, HouseOverview, PollView, ProposalView } from "../../shared/api/community";
import { communityApi } from "../../shared/api/community";
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
    council: vi.fn().mockResolvedValue({ house_id: HOUSE, is_member: false, proposals: [] }),
    propose: vi.fn(),
    councilAnnouncement: vi.fn(),
    councilPoll: vi.fn(),
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

describe("Совет дома и «Предложить вопрос» (D4)", () => {
  const proposal = (patch: Partial<ProposalView> = {}): ProposalView => ({
    id: "pr1", house_id: HOUSE, text: "Поставить велопарковку у второго подъезда", status: "new",
    created_at: "2026-09-26T10:00:00Z", mine: false, poll_id: null, ...patch,
  });
  const council = (patch: Partial<CouncilView> = {}): CouncilView => ({
    house_id: HOUSE, is_member: false, proposals: [], ...patch,
  });
  const noTechWords = () => expect(document.body.textContent?.toLowerCase()).not.toMatch(/тест|демо/);
  const PUBLISHED = "Опубликовано: сообщение уйдёт в чат дома и в ленту «Объявления».";

  it("житель предлагает тему и видит её со статусом «Ждёт рассмотрения»; панели совета нет", async () => {
    const created = proposal({ id: "pr9", text: "Покрасить скамейки во дворе", mine: true });
    const propose = vi.fn().mockResolvedValue(created);
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockResolvedValue(overview),
      council: vi.fn().mockResolvedValue(council()), propose })} houseId={HOUSE} links={links()} />);
    expect(await screen.findByRole("heading", { name: "Предложить вопрос" })).toBeTruthy();
    expect(screen.getByText("Тему увидят совет дома и управляющая компания; её можно вынести на опрос.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Совет дома" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Опубликовать" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Тема или вопрос"), { target: { value: "  Покрасить скамейки во дворе " } });
    fireEvent.click(screen.getByRole("button", { name: "Предложить" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith(HOUSE, "Покрасить скамейки во дворе", expect.any(String)));
    const mine = await screen.findByRole("list", { name: "Мои предложения" });
    expect(within(mine).getByText("Покрасить скамейки во дворе")).toBeTruthy();
    expect(within(mine).getByText("Ждёт рассмотрения")).toBeTruthy();
    expect(screen.getByText(/Тема добавлена/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/отправлено|зарегистрировано|передано в/i);
    noTechWords();
  });

  it("правило сервиса (не больше 3 тем) показывается дословно; повтор идёт с тем же ключом", async () => {
    const rule = "Можно предложить не больше 3 тем, пока их не рассмотрели совет дома или управляющая компания.";
    const propose = vi.fn().mockRejectedValue(new ApiProblem({ status: 422, type: "about:blank", code: "validation_error",
      title: "Request validation failed", detail: rule, trace_id: "t", retryable: false,
      field_errors: [{ field: "text", code: "limit", message: rule }] }));
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockResolvedValue(overview), propose })} houseId={HOUSE} links={links()} />);
    fireEvent.change(await screen.findByLabelText("Тема или вопрос"), { target: { value: "Четвёртая тема" } });
    fireEvent.click(screen.getByRole("button", { name: "Предложить" }));
    expect((await screen.findByRole("alert")).textContent).toBe(rule);
    fireEvent.click(screen.getByRole("button", { name: "Предложить" }));
    await waitFor(() => expect(propose).toHaveBeenCalledTimes(2));
    expect(propose.mock.calls[1][2]).toBe(propose.mock.calls[0][2]);
  });

  it("вынесенное на опрос предложение ведёт к опросу", async () => {
    const nav = links();
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockResolvedValue(overview),
      council: vi.fn().mockResolvedValue(council({ proposals: [proposal({ mine: true, status: "converted", poll_id: "poll-7" })] })) })}
      houseId={HOUSE} links={nav} />);
    expect(await screen.findByText("Вынесено на опрос")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Открыть опрос" }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?view=poll&house=${HOUSE}&poll=poll-7`);
  });

  it("член совета публикует объявление: только после отметки «не реклама», с service_only", async () => {
    const load = vi.fn().mockResolvedValue(council({ is_member: true, proposals: [proposal()] }));
    const councilAnnouncement = vi.fn().mockResolvedValue({ broadcast_id: "b1", status: "scheduled", poll_id: null });
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockResolvedValue(overview), council: load, councilAnnouncement })}
      houseId={HOUSE} links={links()} />);
    const form = (await screen.findByRole("heading", { name: "Объявление от совета" })).closest("form") as HTMLElement;
    expect(screen.getByRole("heading", { name: "Совет дома" })).toBeTruthy();
    fireEvent.change(within(form).getByLabelText("Заголовок"), { target: { value: "Субботник в субботу" } });
    fireEvent.change(within(form).getByLabelText("Текст"), { target: { value: "Сбор у первого подъезда в 10:00." } });
    const publish = within(form).getByRole("button", { name: "Опубликовать" }) as HTMLButtonElement;
    expect(publish.disabled).toBe(true);
    fireEvent.click(within(form).getByLabelText("Это сервисное сообщение, не реклама"));
    fireEvent.click(publish);
    await waitFor(() => expect(councilAnnouncement).toHaveBeenCalledTimes(1));
    const [house, payload, key] = councilAnnouncement.mock.calls[0];
    expect(house).toBe(HOUSE);
    expect(payload).toEqual({ title: "Субботник в субботу", body: "Сбор у первого подъезда в 10:00.", service_only: true });
    expect(key).toEqual(expect.any(String));
    expect(await screen.findByText(PUBLISHED)).toBeTruthy();
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThan(1));
    noTechWords();
  });

  it("член совета выносит предложение жителя на опрос: вопрос из предложения и proposal_id в запросе", async () => {
    const councilPoll = vi.fn().mockResolvedValue({ broadcast_id: "b2", status: "scheduled", poll_id: "poll-9" });
    const nav = links();
    render(<MyHouseScreen api={api({ houseOverview: vi.fn().mockResolvedValue(overview),
      council: vi.fn().mockResolvedValue(council({ is_member: true, proposals: [proposal()] })), councilPoll })}
      houseId={HOUSE} links={nav} />);
    const residents = await screen.findByRole("list", { name: "Предложения жителей" });
    expect(within(residents).getByText("Ждёт рассмотрения")).toBeTruthy();
    fireEvent.click(within(residents).getByRole("button", { name: /^Сделать опросом/ }));
    const form = screen.getByRole("heading", { name: "Опрос от совета" }).closest("form") as HTMLElement;
    const question = within(form).getByLabelText("Вопрос") as HTMLInputElement;
    expect(question.value).toBe("Поставить велопарковку у второго подъезда");
    expect(within(form).getByText(/Опрос по предложению жителя/)).toBeTruthy();
    expect(within(form).getByText("Предварительный опрос. Не является решением общего собрания собственников.")).toBeTruthy();
    fireEvent.change(within(form).getByLabelText("Вариант 1"), { target: { value: "За" } });
    fireEvent.change(within(form).getByLabelText("Вариант 2"), { target: { value: "Против" } });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить вариант" }));
    fireEvent.change(within(form).getByLabelText("Вариант 3"), { target: { value: "Нужно обсудить" } });
    fireEvent.click(within(form).getByLabelText("Это сервисное сообщение, не реклама"));
    fireEvent.click(within(form).getByRole("button", { name: "Опубликовать опрос" }));
    await waitFor(() => expect(councilPoll).toHaveBeenCalledTimes(1));
    const [, payload] = councilPoll.mock.calls[0];
    expect(payload).toMatchObject({
      proposal_id: "pr1", service_only: true,
      poll: { question: "Поставить велопарковку у второго подъезда", options: ["За", "Против", "Нужно обсудить"], multiple: false },
    });
    // По умолчанию голосование идёт трое суток.
    const closes = new Date(payload.poll.closes_at).getTime() - Date.now();
    expect(closes).toBeGreaterThan(2.9 * 86400000);
    expect(closes).toBeLessThan(3.1 * 86400000);
    expect(await screen.findByText(PUBLISHED)).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "Открыть опрос" }));
    expect(nav.navigate).toHaveBeenCalledWith(`/?view=poll&house=${HOUSE}&poll=poll-9`);
  });

  it("запросы совета идут с ключом идемпотентности и телом по контракту", async () => {
    const request = vi.fn().mockResolvedValue({});
    const client = communityApi({ request: request as never });
    await client.councilAnnouncement(HOUSE, { title: "Субботник", body: "В 10:00", service_only: true }, "key-announcement");
    await client.councilPoll(HOUSE, { poll: { question: "Покрасить?", options: ["За", "Против"], multiple: false,
      closes_at: "2026-09-30T10:00:00Z" }, proposal_id: "pr1", service_only: true }, "key-poll");
    await client.propose(HOUSE, "Тема", "key-proposal");
    const [announcementPath, announcement] = request.mock.calls[0] as [string, RequestInit];
    expect(announcementPath).toBe(`/api/v1/houses/${HOUSE}/council/announcements`);
    expect(announcement.method).toBe("POST");
    expect(new Headers(announcement.headers).get("Idempotency-Key")).toBe("key-announcement");
    expect(JSON.parse(String(announcement.body))).toEqual({ title: "Субботник", body: "В 10:00", service_only: true });
    const [pollPath, poll] = request.mock.calls[1] as [string, RequestInit];
    expect(pollPath).toBe(`/api/v1/houses/${HOUSE}/council/polls`);
    expect(new Headers(poll.headers).get("Idempotency-Key")).toBe("key-poll");
    expect(JSON.parse(String(poll.body))).toMatchObject({ proposal_id: "pr1", service_only: true });
    const [proposePath, proposeInit] = request.mock.calls[2] as [string, RequestInit];
    expect(proposePath).toBe(`/api/v1/houses/${HOUSE}/proposals`);
    expect(new Headers(proposeInit.headers).get("Idempotency-Key")).toBe("key-proposal");
    expect(JSON.parse(String(proposeInit.body))).toEqual({ text: "Тема" });
  });
});
