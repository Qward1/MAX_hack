import { test, expect } from "@playwright/test";
import { spawnSync } from "node:child_process";

test.skip(process.env.ND_FIXTURES !== "1", "Requires explicit local notification runtime");

test("ND launch through server resolver, resident observation and provider edit", async ({ page, request }) => {
  async function auth(actor: string) {
    const response = await request.post("/api/v1/auth/test-session", { data: { actor } });
    expect(response.ok()).toBeTruthy();
    return { Authorization: `Bearer ${(await response.json()).access_token}` };
  }
  const resident = await auth("a16-resident");
  const employee = await auth("a16-responsible");
  const me = await (await request.get("/api/v1/me", { headers: employee })).json();
  const house = me.houses[0].id;
  const created = await request.post("/api/v1/reports", { headers: {
    ...resident, "Idempotency-Key": crypto.randomUUID(),
  }, data: { house_id: house, category: "water", description: "ND browser " + crypto.randomUUID() } });
  expect(created.status()).toBe(201);
  const incident = (await created.json()).incident.id;
  const current = await (await request.get(`/api/v1/incidents/${incident}/work-status`, { headers: resident })).json();
  const ticket = current.ticket_id;
  for (const action of ["accept", "start", "work-attempts"]) {
    const view = await (await request.get(`/api/v1/tickets/${ticket}`, { headers: employee })).json();
    const result = await request.post(`/api/v1/tickets/${ticket}/${action}`, { headers: {
      ...employee, "Idempotency-Key": crypto.randomUUID(),
    }, data: { expected_version: view.version,
      ...(action === "work-attempts" ? { public_description: "ND результат для проверки жителем" } : {}) } });
    expect(result.ok()).toBeTruthy();
  }
  function delivery() {
    const result = spawnSync("uv", ["run", "python", "tests/browser/notification_fixture.py", ticket],
      { cwd: "..", encoding: "utf8", env: process.env });
    if (result.status !== 0) throw new Error(result.stderr);
    return JSON.parse(result.stdout);
  }
  await expect.poll(() => delivery()?.status).toBe("accepted");
  const target = delivery();
  await page.goto(`/?test_actor=a16-resident&test_start_param=${target.ref}`);
  await expect(page.getByText("ND результат для проверки жителем")).toBeVisible();
  await expect(page.getByText("Результат из уведомления")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`incident=${incident}`));
  await page.getByRole("button", { name: "Проблема осталась", exact: true }).click();
  await expect(page.getByText("Проблема возвращена в работу.", { exact: true })).toBeVisible();
  await expect.poll(() => delivery()?.reconciled).toBe(true);
  await page.reload();
  await expect(page.getByText("Ваш последний ответ: проблема осталась.")).toBeVisible();
  await page.screenshot({ path: "test-results/nd-resident.png", fullPage: true });
  await page.goto(`/?test_actor=a16-outsider&test_start_param=${target.ref}`);
  await expect(page.getByText("Проблема не найдена", { exact: true })).toBeVisible();
  await expect(page.getByText("ND результат для проверки жителем")).toHaveCount(0);
});
