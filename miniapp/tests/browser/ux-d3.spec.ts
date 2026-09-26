import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

// UX-D3: независимый проход по поверхностям продукта на 390×844 и 1280×800.
// На каждом экране: загрузка завершилась результатом, есть путь назад или
// меню, axe WCAG 2 AA без нарушений, горизонтальной прокрутки нет. Снимки —
// в test-results/ux-d3 для разбора человеком (таблица в scenarios/acceptance.md).
const require = createRequire(import.meta.url);
const SHOTS = "test-results/ux-d3";

function run(script: string, args: string[]) {
  const r = spawnSync("uv", ["run", "python", script, ...args], { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout);
}
const d3 = (...args: string[]) => run("tests/browser/d3_fixture.py", args);
const d2 = (...args: string[]) => run("tests/browser/d2_fixture.py", args);
const enrollOtp = () => run("tests/browser/employee_fixture.py", ["otp"]).code as string;

async function axeCheck(page: Page) {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () =>
    ((await (window as any).axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] } })).violations
      .map((v: any) => ({ id: v.id, targets: v.nodes.map((n: any) => n.target) }))));
  expect(violations, "axe WCAG 2 AA").toEqual([]);
}
async function inspect(page: Page, name: string, width: number) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${name}: no overflow`).toBe(true);
  await axeCheck(page);
  await page.screenshot({ path: `${SHOTS}/${name}-${width}.png`, fullPage: true });
}
async function context(browser: Browser, width: number) {
  const ctx = await browser.newContext({
    viewport: { width, height: width < 500 ? 844 : 800 }, bypassCSP: true, reducedMotion: "reduce",
  });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", route => route.abort());
  return ctx;
}
async function auth(request: APIRequestContext, actor: string) {
  const response = await request.post("/api/v1/auth/test-session", { data: { actor } });
  expect(response.status()).toBe(200);
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}
const key = () => `ux-d3-${Date.now()}-${Math.random().toString(16).slice(2)}`;

let ids: { company: string; house: string };
let refs: { incident: string; card: string; draft: string; poll: string | null };

test.describe.serial("UX-D3 sweep", () => {
  test.skip(process.env.D3_BROWSER_FIXTURES !== "1" || process.env.D2_BROWSER_FIXTURES !== "1",
    "Needs isolated HTTP/PostgreSQL D2 and D3 fixtures");

  test.beforeAll(async ({ request }) => {
    mkdirSync(SHOTS, { recursive: true });
    ids = d3("ids");
    d3("binding");
    const resident = await auth(request, "a16-resident");
    const created = await request.post("/api/v1/reports", {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { house_id: ids.house, category: "lighting",
        description: `Не горит свет на лестничной площадке пятого этажа. ${"Очень длинное описание проблемы. ".repeat(20)}` },
    });
    expect(created.status()).toBe(201);
    const submitted = await request.post(`/api/v1/houses/${ids.house}/reports/submit`, {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { description: "На улице у остановки не горят фонари, темно" },
    });
    expect(submitted.status()).toBe(201);
    const card = (await submitted.json()).route_outcome_id;
    const draft = await request.post("/api/v1/appeal-drafts", {
      headers: resident, data: { house_id: ids.house, route_outcome_id: card },
    });
    const feed = await (await request.get(`/api/v1/houses/${ids.house}/announcements`, { headers: resident })).json();
    const poll = feed.items.find((item: any) => item.poll)?.poll?.poll_id ?? null;
    refs = { incident: (await created.json()).incident.id, card, draft: (await draft.json()).id, poll };
  });

  for (const width of [390, 1280]) {
    test(`resident surfaces at ${width}`, async ({ browser }) => {
      test.setTimeout(240000);
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      const base = `/?test_actor=a16-resident&house=${ids.house}`;
      try {
        const screens: [string, string, string][] = [
          ["board", base, "Проблемы дома"],
          ["my-house", `${base}&view=home`, "Мой дом"],
          ["announcements", `${base}&view=news`, "Объявления"],
          ["works", `${base}&view=works`, "Что сделано в доме"],
          ["my-activity", `${base}&view=mine`, "Мои обращения"],
          ["reception", `${base}&view=reception`, "Запись на приём"],
          ["incident", `${base}&incident=${refs.incident}`, ""],
          ["route-card", `${base}&card=${refs.card}`, "Куда обратиться"],
          ["draft", `${base}&draft=${refs.draft}`, "Черновик обращения"],
        ];
        if (refs.poll) screens.push(["poll", `${base}&view=poll&poll=${refs.poll}`, "Опрос"]);
        for (const [name, url, heading] of screens) {
          await page.goto(url);
          if (heading) await expect(page.getByRole("heading", { level: 1, name: heading }).or(
            page.getByRole("heading", { level: 2, name: heading })).first()).toBeVisible();
          if (name !== "board") {
            // Нет тупика: у вложенного экрана есть «Назад», у раздела — вкладки.
            await expect(
              page.getByRole("button", { name: /Назад/ }).or(page.getByRole("navigation", { name: "Разделы" })).first(),
            ).toBeVisible();
          }
          await inspect(page, `resident-${name}`, width);
        }
        // Назад из раздела ведёт туда, откуда пришли.
        await page.goto(`${base}&view=news`);
        await page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Мой дом" }).click();
        await page.goBack();
        await expect(page.getByRole("heading", { level: 1, name: "Объявления" })).toBeVisible();
      } finally { await ctx.close(); }
    });

    test(`company surfaces at ${width}`, async ({ browser }) => {
      test.setTimeout(240000);
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      const q = `company=${ids.company}&test_actor=a16-admin`;
      try {
        for (const [name, path, heading] of [
          ["overview", `/admin/?${q}`, "Обзор"],
          ["tickets", `/admin/tickets?${q}`, ""],
          ["signals", `/admin/?section=signals&${q}`, ""],
          ["houses", `/admin/houses?${q}`, "Дома"],
          ["staff", `/admin/staff?${q}`, "Сотрудники"],
          ["chats", `/admin/max?${q}`, "MAX-чаты"],
          ["organization", `/admin/organization?${q}`, "Организация"],
          ["mailings", `/admin/mailings?${q}`, "Рассылки"],
          ["notices", `/admin/notices?${q}`, "Уведомления"],
          ["reception", `/admin/reception?${q}`, "Приём"],
        ] as const) {
          await page.goto(path);
          if (heading) await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
          await expect(page.getByRole("navigation", { name: "Разделы кабинета" })).toBeVisible();
          await inspect(page, `company-${name}`, width);
        }
        await page.goto(`/admin/mailings?${q}`);
        await page.getByRole("button", { name: "Новое сообщение" }).click();
        await inspect(page, "company-mailing-form", width);
        const operator = `company=${ids.company}&test_actor=a16-operator`;
        await page.goto(`/admin/?${operator}`);
        await expect(page.getByRole("navigation", { name: "Разделы кабинета" })).toBeVisible();
        await inspect(page, "operator-start", width);
      } finally { await ctx.close(); }
    });
  }

  test("platform, landing and login at both widths", async ({ browser }) => {
    test.setTimeout(240000);
    d2("reset-rate");
    const setup = d2("platform");
    const ctx = await context(browser, 1280);
    const page = await ctx.newPage();
    try {
      await page.goto("/login");
      await page.getByLabel("Логин").fill("d2.platform");
      await page.getByLabel("Пароль", { exact: true }).fill(setup.password);
      await page.getByRole("button", { name: "Войти", exact: true }).click();
      await page.getByLabel("Новый пароль").fill(`UX D3 platform password ${Date.now()}!`);
      await page.getByRole("button", { name: "Продолжить" }).click();
      await page.getByRole("button", { name: "Показать QR-код" }).click();
      await page.getByLabel("Код из приложения").fill(enrollOtp());
      await page.getByRole("button", { name: "Продолжить" }).click();
      await page.getByRole("button", { name: "Коды сохранены — открыть кабинет" }).click();
      await expect(page).toHaveURL(/\/platform-admin\/$/);
      for (const [name, path] of [["overview", "/platform-admin/"], ["mailings", "/platform-admin/mailings"],
        ["companies", "/platform-admin/companies"]] as const) {
        await page.goto(path);
        await expect(page.getByRole("navigation", { name: "Разделы платформы" })).toBeVisible();
        await inspect(page, `platform-${name}`, 1280);
      }
      await page.getByRole("button", { name: "Новое сообщение" }).isVisible().catch(() => false);
      await page.goto("/platform-admin/mailings");
      await page.getByRole("button", { name: "Новое сообщение" }).click();
      await inspect(page, "platform-mailing-form", 1280);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/platform-admin/mailings");
      await inspect(page, "platform-mailings", 390);
    } finally { await ctx.close(); }
    for (const width of [390, 1280]) {
      const guest = await context(browser, width);
      const landing = await guest.newPage();
      try {
        await landing.goto("/site");
        await inspect(landing, "landing", width);
        await landing.goto("/login");
        await inspect(landing, "login", width);
      } finally { await guest.close(); }
    }
  });
});
