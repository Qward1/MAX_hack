import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let houses: Record<string, string>;
function fixture(command: string, id?: string) {
  const result = spawnSync(
    "uv",
    [
      "run",
      "python",
      "tests/browser/ticket_fixture.py",
      command,
      ...(id ? [id] : []),
    ],
    {
      cwd: "..",
      encoding: "utf8",
      env: process.env,
    },
  );
  if (result.status !== 0)
    throw new Error(`Fixture ${command} failed: ${result.stderr}`);
  return JSON.parse(result.stdout.trim());
}
async function auth(request: APIRequestContext, actor: string) {
  const response = await request.post("/api/v1/auth/test-session", {
    data: { actor },
  });
  expect(response.status()).toBe(200);
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}
async function detail(
  request: APIRequestContext,
  id: string,
  actor = "a16-admin",
) {
  const response = await request.get(`/api/v1/tickets/${id}`, {
    headers: await auth(request, actor),
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function command(
  request: APIRequestContext,
  id: string,
  action: string,
  data = {},
  actor = "a16-admin",
) {
  const current = await detail(request, id, actor);
  const response = await request.post(`/api/v1/tickets/${id}/${action}`, {
    headers: {
      ...(await auth(request, actor)),
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: { expected_version: current.version, ...data },
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function createTicket(request: APIRequestContext, house = houses.a1) {
  const response = await request.post("/api/v1/reports", {
    headers: {
      ...(await auth(request, "a16-resident")),
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: {
      house_id: house,
      category: "elevator",
      description: `B14 browser: лифт не работает ${crypto.randomUUID()}`,
      classification_mode: "manual",
    },
  });
  expect(response.status()).toBe(201);
  const incident = (await response.json()).incident;
  const tickets = await request.get(
    `/api/v1/tickets?house_id=${house}&limit=100`,
    { headers: await auth(request, "a16-admin") },
  );
  expect(tickets.status()).toBe(200);
  const ticket = (await tickets.json()).items.find(
    (t: any) => t.incident_id === incident.id,
  );
  expect(ticket).toBeTruthy();
  return { ticket, incident };
}
async function readyAttempt(request: APIRequestContext) {
  const result = await createTicket(request);
  await command(request, result.ticket.id, "accept", {}, "a16-responsible");
  await command(request, result.ticket.id, "start", {}, "a16-responsible");
  const report = await command(
    request,
    result.ticket.id,
    "work-attempts",
    { public_description: "Отрегулирован механизм, лифт работает" },
    "a16-responsible",
  );
  return { ...result, attempt: report.attempt_id };
}
async function observe(
  request: APIRequestContext,
  attempt: string,
  outcome: string,
  actor = "a16-resident",
) {
  const response = await request.post(
    `/api/v1/work-attempts/${attempt}/observations`,
    {
      headers: {
        ...(await auth(request, actor)),
        "Idempotency-Key": crypto.randomUUID(),
      },
      data: { outcome },
    },
  );
  expect(response.status()).toBe(200);
  return response.json();
}
async function openEmployee(
  page: Page,
  id?: string,
  actor = "a16-responsible",
) {
  await page.goto(`/admin/tickets?test_actor=${actor}${id ? `&ticket=${id}` : ""}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  if (id)
    await expect(
      page.getByRole("heading", { name: "Действия по заявке" }),
    ).toBeVisible();
}
async function openResident(
  page: Page,
  incident: string,
  actor = "a16-resident",
) {
  await page.goto(`/?test_actor=${actor}&incident=${incident}`);
  await expect(
    page.getByRole("heading", { name: "Что происходит" }),
  ).toBeVisible();
}
async function workReport(page: Page, text: string) {
  await page
    .getByRole("button", { name: "Сообщить о выполнении", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Что было сделано?" }).fill(text);
  await dialog.getByRole("button", { name: "Сообщить о выполнении" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByText("Результат сохранён. Ожидается проверка жителей."),
  ).toBeVisible();
}
async function axe(page: Page) {
  // Keep production CSP enforced; serve only this test asset from the browser harness.
  await page.route("**/__test_axe.js", route => route.fulfill({
    path: require.resolve("axe-core/axe.min.js"), contentType: "text/javascript",
  }));
  await page.addScriptTag({ url: "/__test_axe.js" });
  await page.unroute("**/__test_axe.js");
  const violations = await page.evaluate(async () =>
    (
      await (window as any).axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
      })
    ).violations.map((v: any) => ({
      id: v.id,
      targets: v.nodes.map((n: any) => n.target),
    })),
  );
  expect(violations).toEqual([]);
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}
test.beforeAll(() => {
  houses = fixture("prepare");
});
test.beforeEach(async ({ page }) => {
  await page.route("https://st.max.ru/**", (route) => route.abort());
});

test("UI-TK-01/02/03/04 scoped queues and foreign house denial", async ({
  page,
  request,
}) => {
  const one = await createTicket(request);
  const two = await createTicket(request, houses.a2);
  await openEmployee(page, undefined, "a16-admin");
  expect(
    await page.evaluate(
      () =>
        document.querySelector('script[src*="st.max.ru"]') === null &&
        !(window as any).WebApp,
    ),
  ).toBe(true);
  await expect(
    page.getByRole("link", {
      name: new RegExp(`^Открыть заявку ${one.ticket.internal_number}:`),
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: new RegExp(`^Открыть заявку ${two.ticket.internal_number}:`),
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "A16 synthetic house b1" }),
  ).toHaveCount(0);
  await openEmployee(page);
  await expect(
    page.getByRole("link", {
      name: new RegExp(`^Открыть заявку ${one.ticket.internal_number}:`),
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "A16 synthetic house a2" }),
  ).toHaveCount(0);
  await page.goto(`/admin/tickets?test_actor=a16-operator&ticket=${two.ticket.id}`);
  await expect(
    page.getByText("Заявка не найдена или больше недоступна."),
  ).toBeVisible();
  await expect(page.getByText(two.incident.description)).toHaveCount(0);
  const denied = await request.get(`/api/v1/tickets?house_id=${houses.a2}`, {
    headers: await auth(request, "a16-operator"),
  });
  expect(denied.status()).toBe(404);
  await openEmployee(page, undefined, "a16-revoked");
  await expect(page.getByText("Нет доступной рабочей очереди")).toBeVisible();
});

test("UI-TK-05/06 concurrent claims refresh the losing employee", async ({
  page,
  browser,
  request,
  baseURL,
}) => {
  const { ticket } = await createTicket(request);
  await command(request, ticket.id, "assign", {
    assignee_id: null,
    reason: "Проверка общей очереди",
  });
  const context = await browser.newContext({ baseURL });
  const other = await context.newPage();
  await openEmployee(page, ticket.id, "a16-operator");
  await openEmployee(other, ticket.id, "a16-responsible");
  await expect(
    page.getByRole("button", { name: "Взять в работу" }),
  ).toBeVisible();
  await expect(
    other.getByRole("button", { name: "Взять в работу" }),
  ).toBeVisible();
  await Promise.all([
    page.getByRole("button", { name: "Взять в работу" }).click(),
    other.getByRole("button", { name: "Взять в работу" }).click(),
  ]);
  const conflict = "Заявку уже принял другой сотрудник. Данные обновлены.";
  await expect
    .poll(
      async () =>
        (await page.getByText(conflict).count()) +
        (await other.getByText(conflict).count()),
    )
    .toBe(1);
  const current = await detail(request, ticket.id);
  expect(current.status).toBe("accepted");
  expect(fixture("snapshot", ticket.id).version).toBe(current.version);
  await context.close();
});

test("UI-TK-07/08/09/13/14/15/21 full product path uses HTTP + PostgreSQL", async ({
  page,
  browser,
  request,
  baseURL,
}) => {
  const { ticket, incident } = await createTicket(request);
  await openEmployee(page);
  await page
    .getByRole("link", {
      name: new RegExp(`^Открыть заявку ${ticket.internal_number}:`),
    })
    .click();
  await page
    .getByRole("button", { name: "Принять заявку", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Начать работу", exact: true })
    .click();
  await workReport(page, "Проверен привод лифта. Выполнена регулировка.");
  const context = await browser.newContext({ baseURL });
  const resident = await context.newPage();
  await resident.route("https://st.max.ru/**", (route) => route.abort());
  await openResident(resident, incident.id);
  await expect(
    resident.getByText("Проверен привод лифта. Выполнена регулировка."),
  ).toBeVisible();
  await resident
    .getByRole("button", { name: "Проблема осталась", exact: true })
    .click();
  await expect(
    resident.getByText("Проблема возвращена в работу."),
  ).toBeVisible();
  expect((await detail(request, ticket.id)).status).toBe("in_progress");
  await page.reload();
  await workReport(page, "Заменён неисправный узел. Лифт проверен повторно.");
  await resident.reload();
  await expect(resident.getByText(/попытка 2/)).toBeVisible();
  await resident
    .getByRole("button", { name: "Исправлено", exact: true })
    .click();
  await expect(
    resident.getByText(
      "Вы подтвердили, что после последней работы проблема устранена.",
    ),
  ).toBeVisible();
  await page.reload();
  await resident.reload();
  await expect(page.locator(".page-header .ds-tag")).toHaveText(
    "Закрыта: жители подтвердили",
  );
  await expect(resident.locator(".resident-work .ds-tag")).toHaveText(
    "Завершена",
  );
  const saved = fixture("snapshot", ticket.id);
  expect(saved).toMatchObject({
    id: ticket.id,
    status: "closed",
    attempts: 2,
    observations: 2,
  });
  expect(saved.version).toBe((await detail(request, ticket.id)).version);
  await page.screenshot({
    path: "test-results/b14-employee-final.png",
    fullPage: true,
  });
  await resident.screenshot({
    path: "test-results/b14-resident-final.png",
    fullPage: true,
  });
  await axe(page);
  await axe(resident);
  await context.close();
});

test("UI-TK-10/27 assignment uses scoped candidates, native focus trap and Escape", async ({
  page,
  request,
}) => {
  const { ticket } = await createTicket(request);
  await openEmployee(page, ticket.id, "a16-admin");
  const trigger = page.getByRole("button", { name: "Назначить исполнителя", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  // Исполнитель — список переключателей (UX-2), только сотрудники этой УК.
  await expect(
    dialog.getByRole("radio", { name: "A16 operator", exact: true }),
  ).toBeAttached();
  await expect(
    dialog.getByRole("radio", { name: "A16 beta-admin", exact: true }),
  ).toHaveCount(0);
  await dialog.getByRole("button", { name: "Закрыть" }).focus();
  await page.keyboard.press("Tab");
  expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(
    true,
  );
  await axe(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await dialog.getByRole("radio", { name: "A16 operator" }).check();
  await dialog
    .getByRole("textbox", { name: "Причина" })
    .fill("Передача дежурному исполнителю");
  await dialog.getByRole("button", { name: "Назначить исполнителя", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("dl").getByText("A16 operator", { exact: true })).toBeVisible();
  await page.reload();
  expect((await detail(request, ticket.id)).assignee_name).toBe("A16 operator");
  await openEmployee(page, ticket.id, "a16-operator");
  await expect(
    page.getByRole("button", { name: "Назначить исполнителя", exact: true }),
  ).toHaveCount(0);
});

test("UI-TK-11 revoked employee loses cached actions and content", async ({
  page,
  request,
}) => {
  const { ticket, incident } = await createTicket(request);
  await openEmployee(page, ticket.id, "a16-operator");
  try {
    fixture("revoke");
    await page.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Действия по заявке" }),
    ).toHaveCount(0);
    await expect(page.getByText(incident.description)).toHaveCount(0);
  } finally {
    fixture("restore");
  }
});

test("UI-TK-16/18/19 late objection, conflict and resident allowlist", async ({
  page,
  request,
}) => {
  const { ticket, incident, attempt } = await readyAttempt(request);
  fixture("link", incident.id);
  await observe(request, attempt, "resolved");
  await openResident(page, incident.id, "a16-neighbor");
  await page
    .getByRole("button", { name: "Проблема осталась", exact: true })
    .click();
  await expect(page.getByText("Проблема возвращена в работу.")).toBeVisible();
  await expect(
    page.getByText(/Результат требует повторной проверки/),
  ).toBeVisible();
  const response = await request.get(
    `/api/v1/incidents/${incident.id}/work-status`,
    { headers: await auth(request, "a16-neighbor") },
  );
  const publicData = await response.json();
  expect(publicData.ticket_id).toBe(ticket.id);
  expect(publicData.observation_conflict).toBe(true);
  for (const key of [
    "assignee_id",
    "assignee_name",
    "performer_name",
    "reported_by",
    "performed_by",
    "routing_reason",
    "actor_id",
    "tenant_id",
    "management_id",
    "resolved_count",
    "unresolved_count",
  ])
    expect(JSON.stringify(publicData)).not.toContain(`"${key}"`);
  await openEmployee(page);
  await page.getByRole("link", { name: "В работе", exact: true }).click();
  await expect(
    page.getByRole("link", {
      name: new RegExp(`^Открыть заявку ${ticket.internal_number}:`),
    }),
  ).toBeVisible();
});

test("UI-TK-17 old attempt never changes the new attempt", async ({
  page,
  request,
}) => {
  const { ticket, incident, attempt } = await readyAttempt(request);
  await openResident(page, incident.id);
  await expect(
    page.getByRole("button", { name: "Исправлено", exact: true }),
  ).toBeVisible();
  await observe(request, attempt, "unresolved");
  const next = await command(
    request,
    ticket.id,
    "work-attempts",
    { public_description: "Повторная работа по новой попытке" },
    "a16-responsible",
  );
  await page.getByRole("button", { name: "Исправлено", exact: true }).click();
  await expect(
    page.getByText(
      "Работа по этой проблеме уже обновилась. Показываем актуальный результат.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("Повторная работа по новой попытке"),
  ).toBeVisible();
  const current = await detail(request, ticket.id);
  expect(current.latest_attempt.id).toBe(next.attempt_id);
  expect(current.status).toBe("verification_pending");
  expect(current.latest_attempt.resolved_count).toBe(0);
});

test("UI-TK-20 foreign resident is denied by HTTP and UI", async ({
  page,
  request,
}) => {
  const { incident } = await readyAttempt(request);
  const denied = await request.get(
    `/api/v1/incidents/${incident.id}/work-status`,
    { headers: await auth(request, "a16-outsider") },
  );
  expect(denied.status()).toBe(404);
  await page.goto(`/?incident=${incident.id}&test_actor=a16-outsider`);
  await expect(
    page.getByText("Проблема не найдена", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(incident.description)).toHaveCount(0);
});

test("UI-TK-24 lost POST response retries the same operation without another attempt", async ({
  page,
  request,
}) => {
  const { ticket } = await createTicket(request);
  await command(request, ticket.id, "accept", {}, "a16-responsible");
  await command(request, ticket.id, "start", {}, "a16-responsible");
  await openEmployee(page, ticket.id);
  const requests: { key: string | undefined; body: string | null }[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/work-attempts"))
      requests.push({
        key: r.headers()["idempotency-key"],
        body: r.postData(),
      });
  });
  await page.route(
    `**/tickets/${ticket.id}/work-attempts`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const saved = await route.fetch();
      expect(saved.status()).toBe(200);
      await route.abort();
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Сообщить о выполнении", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: "Что было сделано?" })
    .fill("Сохранённый отчёт с потерянным ответом");
  await dialog.getByRole("button", { name: "Сообщить о выполнении" }).click();
  await dialog.getByRole("button", { name: "Повторить сохранение" }).click();
  await expect(dialog).toHaveCount(0);
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
  expect(fixture("snapshot", ticket.id).attempts).toBe(1);
});

test("UI-TK-25 employee 409 refreshes authoritative Ticket", async ({
  page,
  request,
}) => {
  const { ticket } = await createTicket(request);
  await openEmployee(page, ticket.id);
  await command(request, ticket.id, "accept", {}, "a16-responsible");
  await page
    .getByRole("button", { name: "Принять заявку", exact: true })
    .click();
  await expect(
    page.getByText("Заявка уже изменилась. Мы обновили данные."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Начать работу", exact: true }),
  ).toBeVisible();
});

for (const width of [390, 768, 1024, 1366])
  test(`UI-TK-22/23/26/27 admin ${width}px long content and keyboard`, async ({
    page,
    request,
  }) => {
    const { ticket } = await createTicket(request);
    const long = "ДлинноеОписаниеБезПробелов".repeat(60);
    await page.setViewportSize({ width, height: 950 });
    await page.route("**/api/v1/me", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.houses[0].address = long;
      await route.fulfill({ response, json: data });
    });
    await page.route(`**/api/v1/tickets/${ticket.id}`, async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      await route.fulfill({
        response,
        json: { ...data, status: "future", allowed_actions: ["future-action"] },
      });
    });
    await openEmployee(page, ticket.id);
    await expect(
      page.getByText("Состояние обновилось", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Сейчас нет доступных действий. Доступна история заявки."),
    ).toBeVisible();
    await noOverflow(page);
    await axe(page);
    const back = page.getByRole("link", { name: "← К заявкам" });
    await back.focus();
    expect(
      await back.evaluate((e) => getComputedStyle(e).outlineStyle),
    ).not.toBe("none");
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "Заявки", exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(".queue-table .cell-main a").first(),
    ).toBeVisible();
    await noOverflow(page);
    await axe(page);
    await page.screenshot({ path: `test-results/b14-admin-${width}.png` });
  });

for (const theme of ["light", "dark"] as const)
  test(`UI-TK-28 resident ${theme} long work result`, async ({
    page,
    request,
  }) => {
    const { incident } = await readyAttempt(request);
    await page.setViewportSize({ width: 320, height: 900 });
    await page.emulateMedia({ colorScheme: theme });
    await page.route(
      `**/incidents/${incident.id}/work-status`,
      async (route) => {
        const response = await route.fetch();
        const data = await response.json();
        data.latest_attempt.public_description = "РезультатБезПробелов".repeat(
          100,
        );
        await route.fulfill({ response, json: data });
      },
    );
    await openResident(page, incident.id);
    await expect(
      page.getByRole("button", { name: "Исправлено", exact: true }),
    ).toBeVisible();
    await noOverflow(page);
    await axe(page);
    await page.screenshot({
      path: `test-results/b14-resident-${theme}.png`,
      fullPage: true,
    });
  });

test("UI-TK-12 management switch removes old operational Ticket", async ({
  page,
  request,
}) => {
  const isolated = fixture("new-house");
  const { ticket, incident } = await createTicket(request, isolated.house);
  await openEmployee(page, ticket.id, "a16-admin");
  fixture("switch", isolated.management);
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(
    page.getByText("Заявка не найдена или больше недоступна."),
  ).toBeVisible();
  await expect(page.getByText(incident.description)).toHaveCount(0);
  const denied = await request.get(`/api/v1/tickets/${ticket.id}`, {
    headers: await auth(request, "a16-beta-admin"),
  });
  expect(denied.status()).toBe(404);
});

test("422 is attached to the work field; correction is a new intentional operation", async ({
  page,
  request,
}) => {
  const { ticket } = await createTicket(request);
  await command(request, ticket.id, "accept", {}, "a16-responsible");
  await command(request, ticket.id, "start", {}, "a16-responsible");
  await openEmployee(page, ticket.id);
  await page.route(
    `**/tickets/${ticket.id}/work-attempts`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 422,
        contentType: "application/problem+json",
        json: {
          status: 422,
          retryable: false,
          detail: "PRIVATE VALIDATION DETAIL",
          field_errors: [
            {
              field: "public_description",
              code: "invalid",
              message: "PRIVATE FIELD DETAIL",
            },
          ],
        },
      });
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Сообщить о выполнении", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  const input = dialog.getByRole("textbox", { name: "Что было сделано?" });
  await input.fill("Содержательный отчёт для проверки валидации");
  await dialog.getByRole("button", { name: "Сообщить о выполнении" }).click();
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(
    dialog.getByText(/Введите описание выполненной работы/),
  ).toBeVisible();
  await expect(page.getByText(/PRIVATE/)).toHaveCount(0);
  await input.fill("Исправленное описание выполненных работ");
  await dialog.getByRole("button", { name: "Сообщить о выполнении" }).click();
  await expect(dialog).toHaveCount(0);
  expect(fixture("snapshot", ticket.id).attempts).toBe(1);
});

test("409 in an open work dialog preserves text and announces refreshed state inside the dialog", async ({
  page,
  request,
}) => {
  const { ticket } = await createTicket(request);
  await command(request, ticket.id, "accept", {}, "a16-responsible");
  await command(request, ticket.id, "start", {}, "a16-responsible");
  await openEmployee(page, ticket.id);
  await page
    .getByRole("button", { name: "Сообщить о выполнении", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  const input = dialog.getByRole("textbox", { name: "Что было сделано?" });
  await input.fill("Мой ещё не отправленный текст");
  await command(
    request,
    ticket.id,
    "work-attempts",
    { public_description: "Результат уже сохранён в другой сессии" },
    "a16-responsible",
  );
  await dialog
    .getByRole("button", { name: "Сообщить о выполнении", exact: true })
    .click();
  await expect(
    dialog.getByText("Заявка уже изменилась. Мы обновили данные."),
  ).toBeVisible();
  await expect(input).toHaveValue("Мой ещё не отправленный текст");
  await expect(
    dialog.getByRole("button", { name: "Сообщить о выполнении", exact: true }),
  ).toBeDisabled();
  expect(fixture("snapshot", ticket.id).attempts).toBe(1);
});
