import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../../shared/api/client";
import { type Observation, type WorkStatus } from "../../shared/api/tickets";
import { apiWith, capabilities, deferred, error } from "../../test/fixtures";
import {
  ResidentWorkProgress,
  staleAttemptMessage,
} from "./ResidentWorkProgress";
import { ticketActions, ticketStatus } from "./presentation";

const attempt = {
  id: "attempt-1",
  number: 1,
  public_description: "Восстановлено освещение",
  rework_required: false,
  created_at: "2026-09-18T10:00:00Z",
};
const work: WorkStatus = {
  incident_id: "incident-1",
  ticket_id: "ticket-1",
  internal_number: "T-17",
  status: "verification_pending",
  version: 4,
  created_at: attempt.created_at,
  updated_at: attempt.created_at,
  latest_attempt: attempt,
  observation_conflict: false,
  my_latest_observation: null,
  deadlines: [],
  allowed_actions: ["observe_result"],
};
const receipt: Observation = {
  observation: {
    id: "observation-1",
    attempt_id: attempt.id,
    outcome: "resolved",
    comment: null,
    corrects_id: null,
    revision: 1,
    created_at: attempt.created_at,
  },
  target_attempt_id: attempt.id,
  applied_to_current: true,
  state_changed: true,
  effect_version: 5,
  replayed: false,
  current: { ...work, status: "closed", allowed_actions: ["observe_result"] },
};
function setup(initial: WorkStatus = work) {
  const client = apiWith();
  vi.mocked(client.workStatus).mockResolvedValue(initial);
  vi.mocked(client.observe).mockResolvedValue(receipt);
  render(<ResidentWorkProgress client={client} incidentId="incident-1" />);
  return client;
}

describe("B-14 resident actions", () => {
  it("UI-TK-13 latest public attempt; actions come from API, not status", async () => {
    setup({ ...work, status: "new", allowed_actions: [] });
    await screen.findByText(attempt.public_description);
    expect(screen.queryByRole("button", { name: "Исправлено" })).toBeNull();
  });
  it("UI-TK-14/21 waits for GET; does not render the optimistic POST snapshot", async () => {
    const client = setup();
    const read = deferred<WorkStatus>();
    await screen.findByRole("button", { name: "Исправлено" });
    vi.mocked(client.workStatus).mockReturnValueOnce(read.promise);
    fireEvent.click(screen.getByRole("button", { name: "Исправлено" }));
    await waitFor(() => expect(client.observe).toHaveBeenCalledOnce());
    expect(screen.queryByText("Завершено")).toBeNull();
    expect(client.observe).toHaveBeenCalledWith(
      attempt.id,
      { outcome: "resolved" },
      expect.any(String),
    );
    await act(async () =>
      read.resolve({
        ...work,
        status: "in_progress",
        observation_conflict: true,
        my_latest_observation: receipt.observation,
      }),
    );
    expect(await screen.findByText("В работе")).toBeTruthy();
    expect(screen.getByText(/Наблюдения жителей расходятся/)).toBeTruthy();
    expect(screen.queryByText("Завершено")).toBeNull();
  });
  it("UI-TK-16 exposes a late objection through allowed_actions after closed", async () => {
    const client = setup({ ...work, status: "closed" });
    await screen.findByRole("button", { name: "Проблема осталась" });
    vi.mocked(client.workStatus).mockResolvedValue({
      ...work,
      status: "in_progress",
      my_latest_observation: { ...receipt.observation, outcome: "unresolved" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проблема осталась" }));
    expect(
      await screen.findByText("Проблема возвращена в работу."),
    ).toBeTruthy();
  });
  it("UI-TK-17 handles the actual historical-result contract without claiming current verification", async () => {
    const client = setup();
    await screen.findByRole("button", { name: "Исправлено" });
    vi.mocked(client.observe).mockResolvedValue({
      ...receipt,
      applied_to_current: false,
    });
    vi.mocked(client.workStatus).mockResolvedValue({
      ...work,
      latest_attempt: {
        ...attempt,
        id: "attempt-2",
        number: 2,
        public_description: "Новая работа",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Исправлено" }));
    expect(await screen.findByText(staleAttemptMessage)).toBeTruthy();
    expect(screen.getByText("Новая работа")).toBeTruthy();
    expect(screen.queryByText(/Вы подтвердили/)).toBeNull();
  });
  it("UI-TK-24 duplicate click + uncertain retry keeps attempt, payload and key", async () => {
    const client = setup();
    await screen.findByRole("button", { name: "Исправлено" });
    vi.mocked(client.observe).mockRejectedValueOnce(
      new TypeError("private network detail"),
    );
    const button = screen.getByRole("button", { name: "Исправлено" });
    fireEvent.click(button);
    fireEvent.click(button);
    await screen.findByRole("button", { name: "Повторить сохранение" });
    expect(client.observe).toHaveBeenCalledOnce();
    fireEvent.click(
      screen.getByRole("button", { name: "Повторить сохранение" }),
    );
    await waitFor(() => expect(client.observe).toHaveBeenCalledTimes(2));
    expect(vi.mocked(client.observe).mock.calls[1]).toEqual(
      vi.mocked(client.observe).mock.calls[0],
    );
    expect(screen.queryByText("private network detail")).toBeNull();
  });
  it("a successful POST followed by failed GET retries the read only", async () => {
    const client = setup();
    await screen.findByRole("button", { name: "Исправлено" });
    vi.mocked(client.workStatus).mockRejectedValueOnce(error(503));
    fireEvent.click(screen.getByRole("button", { name: "Исправлено" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Повторить сохранение" }),
    );
    await screen.findByText("Ответ сохранён. Показаны актуальные данные.");
    expect(client.observe).toHaveBeenCalledOnce();
    expect(client.workStatus).toHaveBeenCalledTimes(3);
  });
  it.each([401, 403, 404])(
    "UI-TK-20 clears private projection after %i",
    async (status) => {
      const client = setup();
      await screen.findByRole("button", { name: "Исправлено" });
      vi.mocked(client.observe).mockRejectedValue(error(status));
      vi.mocked(client.workStatus).mockRejectedValue(error(status));
      fireEvent.click(screen.getByRole("button", { name: "Исправлено" }));
      await waitFor(() =>
        expect(screen.queryByText(attempt.public_description)).toBeNull(),
      );
      expect(screen.queryByText("PRIVATE")).toBeNull();
    },
  );
  it("UI-TK-25 409 reloads safe projection and shows stale guidance", async () => {
    const client = setup();
    await screen.findByRole("button", { name: "Исправлено" });
    vi.mocked(client.observe).mockRejectedValue(error(409));
    fireEvent.click(screen.getByRole("button", { name: "Исправлено" }));
    expect(await screen.findByText(staleAttemptMessage)).toBeTruthy();
    expect(client.workStatus).toHaveBeenCalledTimes(2);
  });
  it.each([422, 429, 503])("safe mutation failure %i", async (status) => {
    const client = setup();
    await screen.findByRole("button", { name: "Исправлено" });
    vi.mocked(client.observe).mockRejectedValue(error(status));
    fireEvent.click(screen.getByRole("button", { name: "Исправлено" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("PRIVATE")).toBeNull();
  });
  it("UI-TK-22/23 unknown values are neutral and unknown/disabled actions cannot execute", async () => {
    setup({
      ...work,
      status: "future",
      allowed_actions: [
        "evil",
        {
          code: "observe_result",
          enabled: false,
          reason: "Проверка временно недоступна",
        },
      ],
    });
    expect(await screen.findByText("Состояние обновилось")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Исправлено" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("Проверка временно недоступна")).toBeTruthy();
    expect(ticketActions(["evil"])).toEqual([]);
    expect(ticketStatus("future")).toBe("Состояние обновилось");
  });
  it("employee authentication never reads MAX initData and production ignores test actor", async () => {
    window.WebApp = { initData: "must-not-use" };
    window.history.replaceState(null, "", "/admin/?test_actor=a16-admin");
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      stage: "login", csrf_token: "synthetic-csrf", recovery_codes: [],
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(
      new ApiClient("employee").authenticate({
        ...capabilities,
        environment: "production",
      }),
    ).rejects.toMatchObject({ problem: { status: 401 } });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/auth/employee/session");
  });
});
