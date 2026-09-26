import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminClient, type Schema } from "./administration";
import { AddressListForm, BatchApprove, parseAddresses } from "./HouseBatch";

afterEach(() => vi.restoreAllMocks());

function posts(request: { mock: { calls: unknown[][] } }): [string, RequestInit][] {
  return request.mock.calls.filter(call => (call[1] as RequestInit | undefined)?.method === "POST") as [string, RequestInit][];
}

describe("D5: дома пачкой", () => {
  it("список адресов — по одному на строку, пустые строки пропускаются", () => {
    expect(parseAddresses("Казань, Пилотная, 1\r\n\n  Казань, Пилотная, 2  \n")).toEqual(["Казань, Пилотная, 1", "Казань, Пилотная, 2"]);
  });

  it("администратор УК вставляет список и видит результат по каждому адресу", async () => {
    const answer: Schema["HouseBatchSubmitted"] = {
      created: 1, skipped: 1,
      items: [
        { address: "Казань, Пилотная, 1", outcome: "created", request_id: "r1" },
        { address: "Казань, Пилотная, 1", outcome: "duplicate", request_id: null },
      ],
    };
    const request = vi.spyOn(adminClient, "request").mockResolvedValue(answer);
    render(<AddressListForm base="/api/v1/companies/c1" onDone={() => undefined} />);
    const submit = screen.getByRole("button", { name: "Подать заявки на дома" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Адреса домов"), { target: { value: "Казань, Пилотная, 1\nКазань, Пилотная, 1" } });
    expect(screen.getByText("2 адреса")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Основание"), { target: { value: "Договоры управления" } });
    fireEvent.click(screen.getByRole("button", { name: "Подать заявки на дома" }));
    await screen.findByText("Создано заявок: 1.");
    expect(screen.getByText("Повтор в списке")).toBeTruthy();
    const [[path, init]] = posts(request);
    expect(path).toBe("/api/v1/companies/c1/house-management-requests/batch");
    const body = JSON.parse(String(init.body));
    expect(body.addresses).toEqual(["Казань, Пилотная, 1", "Казань, Пилотная, 1"]);
    expect(body.basis_text).toBe("Договоры управления");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
  });

  it("больше 200 адресов отправить нельзя, причина видна", () => {
    render(<AddressListForm base="/api/v1/companies/c1" onDone={() => undefined} />);
    const many = Array.from({ length: 201 }, (_, index) => `Казань, Длинная, ${index + 1}`).join("\n");
    fireEvent.change(screen.getByLabelText("Адреса домов"), { target: { value: many } });
    expect(screen.getByText(/Слишком много: 201/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Подать заявки на дома" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("платформа одобряет выбранные заявки с одним регионом и видит отказ по дому", async () => {
    const requests = [
      { id: "r1", requested_address: "Казань, Пилотная, 1", status: "submitted", source_application_id: "a1" },
      { id: "r2", requested_address: "Казань, Пилотная, 2", status: "under_review", source_application_id: null },
      { id: "r3", requested_address: "Казань, Пилотная, 3", status: "approved", source_application_id: null },
    ] as Schema["HouseRequestView"][];
    const answer: Schema["HouseBatchApproved"] = {
      approved: 1, already_approved: 0, failed: 1,
      items: [
        { request_id: "r1", outcome: "approved", house_id: "h1", management_id: "m1", message: null },
        { request_id: "r2", outcome: "conflict", message: "Период пересекается с действующим управлением", house_id: null, management_id: null },
      ],
    };
    const request = vi.spyOn(adminClient, "request").mockResolvedValue(answer);
    render(<BatchApprove requests={requests} packs={[]} refresh={() => undefined}
      regionFields={(region, onRegion) => <label>Регион<select name="region" value={region} onChange={e => onRegion(e.target.value)}>
        <option value="">—</option><option value="RU-TA">Татарстан</option></select></label>} />);
    const list = screen.getByRole("group", { name: /Заявки/ });
    expect(within(list).queryByText("Казань, Пилотная, 3")).toBeNull(); // одобренная не предлагается
    expect(within(list).getByText("из заявки УК")).toBeTruthy();
    fireEvent.click(within(list).getByLabelText("Выбрать все открытые"));
    fireEvent.change(screen.getByLabelText("Регион"), { target: { value: "RU-TA" } });
    fireEvent.change(screen.getByLabelText("Основание решения"), { target: { value: "Реестр УК" } });
    fireEvent.click(screen.getByRole("button", { name: "Одобрить выбранные (2)" }));
    await screen.findByText("Одобрено: 1.");
    expect(screen.getByText(/Период пересекается/)).toBeTruthy();
    const [[path, init]] = posts(request);
    expect(path).toBe("/api/v1/platform/house-management-requests/approve-batch");
    const body = JSON.parse(String(init.body));
    expect(body.request_ids.sort()).toEqual(["r1", "r2"]);
    expect(body.region_code).toBe("RU-TA");
    await waitFor(() => expect(screen.getByRole("button", { name: "Одобрить выбранные (0)" })).toBeTruthy());
  });
});
