import { expect, test, type APIRequestContext, type Browser } from "@playwright/test";
import { spawnSync } from "node:child_process";

// F1: экраны обновляются сами (§2.3, U-06, U-12) и 403 раздела не теряет
// сессию (B-08, TC-027 шаг 1). Изменение делает другая сессия через API —
// экран показывает его не позже чем через 20 с без перезагрузки.
// Стенд — как у UX-D3: HTTP + PostgreSQL с фикстурами D2/D3 (miniapp/README.md).
function run(script: string, args: string[]) {
  const r = spawnSync("uv", ["run", "python", script, ...args], { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout.trim().split("\n").at(-1) ?? "{}");
}
const d3 = (...args: string[]) => run("tests/browser/d3_fixture.py", args);
const d2 = (...args: string[]) => run("tests/browser/d2_fixture.py", args);
const key = () => `f1-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function auth(request: APIRequestContext, actor: string) {
  const response = await request.post("/api/v1/auth/test-session", { data: { actor } });
  expect(response.status()).toBe(200);
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}
async function context(browser: Browser, width = 1280) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 500 ? 844 : 800 }, reducedMotion: "reduce" });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", (route) => route.abort());
  return ctx;
}

test.describe.serial("F1 refresh and access", () => {
  test.skip(process.env.D3_BROWSER_FIXTURES !== "1" || process.env.D2_BROWSER_FIXTURES !== "1",
    "Needs isolated HTTP/PostgreSQL D2 and D3 fixtures");
  let ids: { company: string; house: string };
  test.beforeAll(() => { ids = d3("ids"); });

  test("status changed by another session appears in the list and the card within 20 s", async ({ browser, request }) => {
    test.setTimeout(90000);
    const resident = await auth(request, "a16-resident");
    const created = await request.post("/api/v1/reports", {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { house_id: ids.house, category: "elevator", description: `Лифт стоит на девятом этаже ${key()}` },
    });
    expect(created.status()).toBe(201);
    const incident = (await created.json()).incident.id;
    const responsible = await auth(request, "a16-responsible");
    const list = await (await request.get(`/api/v1/tickets?house_id=${ids.house}&limit=50`, { headers: responsible })).json();
    const ticket = list.items.find((item: { incident_id: string }) => item.incident_id === incident);
    const ctx = await context(browser);
    const page = await ctx.newPage();
    const detail = await ctx.newPage();
    try {
      await page.goto(`/admin/tickets?test_actor=a16-admin&view=all`);
      const row = page.locator("tr, li, article").filter({ hasText: ticket.internal_number }).first();
      await expect(row).toContainText("Новая");
      await detail.goto(`/admin/?test_actor=a16-admin&ticket=${ticket.id}`);
      await expect(detail.getByRole("heading", { level: 1 })).toBeVisible();
      const accepted = await request.post(`/api/v1/tickets/${ticket.id}/accept`, {
        headers: { ...responsible, "Idempotency-Key": key() }, data: { expected_version: ticket.version },
      });
      expect(accepted.status()).toBe(200);
      // Опрос раз в 15 с, пока вкладка видима: без перезагрузки не позже 20 с.
      await expect(row).toContainText("Принята", { timeout: 20000 });
      await expect(detail.locator(".page-header")).toContainText("Принята", { timeout: 20000 });
    } finally {
      await ctx.close();
    }
  });

  test("a house approved for the company appears in «Дома» without reload (U-06)", async ({ browser }) => {
    test.setTimeout(90000);
    const ctx = await context(browser);
    const page = await ctx.newPage();
    try {
      await page.goto("/admin/houses?test_actor=a16-admin");
      await expect(page.getByRole("heading", { level: 1, name: "Дома" })).toBeVisible();
      const address = `Казань, ул. Обновляемая, ${Date.now() % 100000}`;
      d2("house-company", ids.company, address);
      await expect(page.getByRole("heading", { name: address })).toBeVisible({ timeout: 20000 });
    } finally {
      await ctx.close();
    }
  });

  test("a section of another role says so and keeps the session (B-08)", async ({ browser }) => {
    const ctx = await context(browser);
    const page = await ctx.newPage();
    try {
      await page.goto("/admin/staff?test_actor=a16-operator");
      await expect(page.getByRole("heading", { level: 1, name: "Раздел недоступен" })).toBeVisible();
      await expect(page.getByText("Вход в кабинет")).toHaveCount(0);
      await page.locator("aside").getByRole("link", { name: /^Заявки/ }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Заявки" })).toBeVisible();
    } finally {
      await ctx.close();
    }
  });

  test("an address the cabinet does not have is not blamed on the role", async ({ browser }) => {
    const ctx = await context(browser);
    const page = await ctx.newPage();
    try {
      await page.goto("/admin/no-such-section?test_actor=a16-admin");
      await expect(page.getByRole("heading", { level: 1, name: "Такой страницы нет" })).toBeVisible();
      await expect(page.getByText("Этот раздел доступен другой роли")).toHaveCount(0);
      await expect(page.getByText("Вход в кабинет")).toHaveCount(0);
    } finally {
      await ctx.close();
    }
  });
});
