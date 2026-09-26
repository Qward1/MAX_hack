import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { HouseCouncil, HouseList } from "./CompanyPages";

afterEach(() => vi.restoreAllMocks());

const BASE = "/api/v1/companies/c1";
const house = { house_id: "h1", management_id: "m1", address: "Казань, Синтетическая улица, 1", valid_from: "2026-09-01T00:00:00Z",
  open_ticket_count: 0, operator_count: 1, responsible_count: 0, bindings: [] } as unknown as Schema["CompanyHouseView"];
const proposal: Schema["ProposalView"] = { id: "p1", house_id: "h1", text: "Поставить велопарковку у второго подъезда",
  status: "new", created_at: "2026-09-26T10:00:00Z", mine: false, poll_id: null };
const adminView: Schema["CouncilAdminView"] = {
  house_id: "h1", can_manage: true,
  members: [{ user_id: "u1", display_name: "Анна Петрова", since: "2026-09-20T10:00:00Z" }],
  residents: [
    { user_id: "u1", display_name: "Анна Петрова", is_member: true },
    { user_id: "u2", display_name: "Борис Иванов", is_member: false },
  ],
  proposals: [proposal, { ...proposal, id: "p2", text: "Покрасить скамейки", status: "converted", poll_id: "poll-1" }],
};
const operatorView: Schema["CouncilAdminView"] = { ...adminView, can_manage: false, residents: [] };

function route(view: Schema["CouncilAdminView"], extra: (path: string, init?: RequestInit) => unknown = () => view) {
  return vi.spyOn(adminClient, "request").mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === `${BASE}/houses/h1/council` && !init?.method) return view as never;
    return extra(path, init) as never;
  });
}
function open() {
  const summary = screen.getByText("Совет дома");
  const details = summary.closest("details") as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}
const posts = (request: ReturnType<typeof route>) =>
  request.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST") as [string, RequestInit][];

describe("Совет дома в кабинете УК (D4)", () => {
  it("данные загружаются только при раскрытии секции", async () => {
    const request = route(adminView);
    render(<HouseCouncil base={BASE} house={house} />);
    expect(request).not.toHaveBeenCalled();
    open();
    expect(await screen.findByText("Анна Петрова")).toBeTruthy();
    expect(request).toHaveBeenCalledWith(`${BASE}/houses/h1/council`, expect.anything());
  });

  it("администратор отмечает жителя в совет с основанием: в запросе user_id и reason", async () => {
    const request = route(adminView, () => adminView);
    const { container } = render(<HouseCouncil base={BASE} house={house} />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Отметить в совет: Борис Иванов" }));
    expect(screen.queryByRole("button", { name: "Отметить в совет: Анна Петрова" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Основание"), { target: { value: "Избран на общем собрании" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить: отметить в совет" }));
    await waitFor(() => expect(posts(request)).toHaveLength(1));
    const [path, init] = posts(request)[0];
    expect(path).toBe(`${BASE}/houses/h1/council/members`);
    expect(JSON.parse(String(init.body))).toEqual({ user_id: "u2", reason: "Избран на общем собрании" });
    expect(await screen.findByText("Борис Иванов отмечен(а) в совете дома.")).toBeTruthy();
    expect(container.textContent?.toLowerCase()).not.toMatch(/тест|демо/);
  });

  it("администратор снимает члена совета с основанием", async () => {
    const request = route(adminView, () => ({ ...adminView, members: [] }));
    render(<HouseCouncil base={BASE} house={house} />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Снять из совета: Анна Петрова" }));
    fireEvent.change(screen.getByLabelText("Основание"), { target: { value: "Житель попросил снять отметку" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить: снять" }));
    await waitFor(() => expect(posts(request)).toHaveLength(1));
    const [path, init] = posts(request)[0];
    expect(path).toBe(`${BASE}/houses/h1/council/members/u1/revoke`);
    expect(JSON.parse(String(init.body))).toEqual({ reason: "Житель попросил снять отметку" });
  });

  it("«Сделать опросом» создаёт черновик с ключом идемпотентности и ведёт в «Рассылки»", async () => {
    const request = route(adminView, () => ({ id: "b1", kind: "poll", status: "draft" }));
    render(<HouseCouncil base={BASE} house={house} />);
    open();
    const buttons = await screen.findAllByRole("button", { name: /^Сделать опросом/ });
    expect(buttons).toHaveLength(1); // вынесенное на опрос повторно не выносится
    expect(screen.getByText("Вынесено на опрос")).toBeTruthy();
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(posts(request)).toHaveLength(1));
    const [path, init] = posts(request)[0];
    expect(path).toBe(`${BASE}/proposals/p1/poll`);
    expect(new Headers(init.headers).get("Idempotency-Key")).toBeTruthy();
    expect(await screen.findByText("Черновик опроса создан — откройте раздел «Рассылки», проверьте и отправьте.")).toBeTruthy();
  });

  it("оператор видит состав совета и предложения, но не меняет их", async () => {
    route(operatorView);
    const { container } = render(<HouseCouncil base={BASE} house={house} />);
    open();
    expect(await screen.findByText("Анна Петрова")).toBeTruthy();
    expect(screen.getByText("Поставить велопарковку у второго подъезда")).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: /Отметить в совет/ })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /Снять/ })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /Сделать опросом/ })).toHaveLength(0);
    expect(screen.getByText(/Состав совета меняет администратор УК/)).toBeTruthy();
    expect(container.textContent?.toLowerCase()).not.toMatch(/тест|демо/);
  });

  it("секция есть и у дома в списке «Мои дома» оператора", () => {
    route(operatorView);
    const { container } = render(<HouseList houses={[house]} base={BASE} />);
    expect(within(container).getByText("Совет дома")).toBeTruthy();
  });
});
