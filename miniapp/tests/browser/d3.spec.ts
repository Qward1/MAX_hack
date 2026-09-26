import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

// D3: профиль УК и «Мой дом», настройки бота в чате, рассылка и опрос от
// черновика до статистики, лента и голос жителя, выполненные работы, «Мои
// обращения». Реальный API и PostgreSQL; MAX на стенде выключен.
const require = createRequire(import.meta.url);

function fixture(...args: string[]) {
  const r = spawnSync("uv", ["run", "python", "tests/browser/d3_fixture.py", ...args], {
    cwd: "..", encoding: "utf8", env: process.env,
  });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout);
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}
async function axeCheck(page: Page) {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () =>
    ((await (window as any).axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] } })).violations
      .map((v: any) => ({ id: v.id, targets: v.nodes.map((n: any) => n.target) }))));
  expect(violations).toEqual([]);
}
async function context(browser: Browser, width: number, height = 900) {
  const ctx = await browser.newContext({ viewport: { width, height }, bypassCSP: true, reducedMotion: "reduce" });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", route => route.abort());
  return ctx;
}
async function auth(request: APIRequestContext, actor: string) {
  const response = await request.post("/api/v1/auth/test-session", { data: { actor } });
  expect(response.status()).toBe(200);
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}
const key = () => `d3-browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;

// Уникальные названия: сценарий повторяем на том же стенде.
const RUN = Date.now().toString().slice(-6);
const TITLE = `Промывка системы отопления ${RUN}`;
const QUESTION = `Какой цвет стен выбрать? ${RUN}`;
const LONG_WORD = "Сверхдлинноесловобезпробеловкотороенедолжноломатьвёрсткунаузкомэкране".repeat(3);
const LONG_BODY = `${"Плановые работы в подвале: промывка и опрессовка системы отопления. ".repeat(12)}${LONG_WORD}`;

let ids: { company: string; house: string; other_house: string; foreign_house: string };

test.describe.serial("D3 community", () => {
  test.skip(process.env.D3_BROWSER_FIXTURES !== "1", "Needs isolated HTTP/PostgreSQL D3 fixtures");

  test.beforeAll(() => {
    ids = fixture("ids");
    fixture("binding");
  });

  test("cabinet: profile, chat settings, announcement and poll from draft to statistics", async ({ browser }) => {
    test.setTimeout(180000);
    const ctx = await context(browser, 1280);
    const page = await ctx.newPage();
    const q = `company=${ids.company}&test_actor=a16-admin`;
    try {
      await page.goto(`/admin/organization?${q}`);
      await expect(page.getByRole("heading", { name: "Контакты для жителей" })).toBeVisible();
      await page.getByLabel("Аварийно-диспетчерская служба (телефон)").fill("+7 843 000-00-02");
      await page.getByLabel("Часы работы").fill("Пн–Пт 9:00–18:00");
      await page.getByLabel("Сайт").fill("javascript:alert(1)");
      await page.getByRole("button", { name: "Сохранить контакты" }).click();
      await expect(page.getByRole("alert")).toContainText("Проверьте поля");
      await page.getByLabel("Сайт").fill("https://uk.example.invalid");
      await page.getByRole("button", { name: "Сохранить контакты" }).click();
      await expect(page.getByText("Контакты сохранены.")).toBeVisible();
      await axeCheck(page);

      await page.goto(`/admin/max?${q}`);
      await page.getByText("Что бот публикует в этом чате").first().click();
      await expect(page.getByText(/Памятка безопасности и сообщение о чтении чата не отключаются/).first()).toBeVisible();
      // Переключение текущего состояния: сценарий повторяем на том же стенде.
      const quiet = page.getByLabel("Без тихих часов").first();
      const wasOff = await quiet.isChecked();
      await quiet.setChecked(!wasOff);
      await page.getByRole("button", { name: "Сохранить настройки" }).first().click();
      await expect(page.getByText("Настройки сохранены.").first()).toBeVisible();
      await expect(page.getByText(wasOff ? /Тихие часы: 22:00–08:00 МСК/ : /Тихие часы: выключены/).first()).toBeVisible();
      await axeCheck(page);

      await page.goto(`/admin/mailings?${q}`);
      await expect(page.getByRole("heading", { name: "Рассылки", level: 1 })).toBeVisible();
      await page.getByRole("button", { name: "Новое сообщение" }).click();
      await expect(page.getByText("Только сервисные сообщения для жителей. Реклама запрещена.")).toBeVisible();
      await page.getByLabel("Тема объявления").selectOption("works");
      await page.getByLabel("Заголовок").fill(TITLE);
      await page.getByLabel(/^Текст/).fill(LONG_BODY);
      await page.getByLabel("Личные сообщения жителям").check();
      await page.getByRole("button", { name: "Создать черновик" }).click();
      await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();
      await page.getByRole("button", { name: "Предпросмотр получателей" }).click();
      await expect(page.getByRole("table", { name: "Предпросмотр получателей" })).toBeVisible();
      await axeCheck(page);
      const send = page.getByRole("button", { name: "Подтвердить и отправить" });
      await expect(send).toBeDisabled();
      await page.getByLabel("Это сервисное сообщение для жителей, не реклама").check();
      await send.click();
      await expect(page.getByText("Запланировано").first()).toBeVisible();
      fixture("send");
      // Живая проверка D3: карточка сама доходит до отправки, без возврата к списку.
      await expect(page.getByRole("table", { name: "Статистика отправки" })).toBeVisible({ timeout: 10000 });
      await expect(page.getByText("Отправлено").first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Исправить текст" })).toBeVisible();
      await noOverflow(page);
      await axeCheck(page);

      await page.getByRole("button", { name: "← К списку" }).click();
      await page.getByRole("button", { name: "Новое сообщение" }).click();
      await page.getByLabel("Опрос").check();
      await page.getByLabel("Заголовок").fill("Покраска подъезда");
      await page.getByLabel("Вопрос").fill(QUESTION);
      await page.getByLabel("Вариант 1").fill("Бежевый");
      await page.getByLabel("Вариант 2").fill("Светло-серый");
      await page.getByRole("button", { name: "Создать черновик" }).click();
      await expect(page.getByText(QUESTION)).toBeVisible();
      await page.getByLabel("Это сервисное сообщение для жителей, не реклама").check();
      await page.getByRole("button", { name: "Подтвердить и отправить" }).click();
      await expect(page.getByText("Запланировано").first()).toBeVisible();
      fixture("send");
      await page.goto(`/admin/?${q}`);
      await expect(page.getByRole("heading", { name: "Обзор", level: 1 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Опросы жителей" })).toBeVisible();
    } finally { await ctx.close(); }
  });

  test("resident: my house, announcements, poll vote, works and my activity at 390 px", async ({ browser, request }) => {
    test.setTimeout(180000);
    // Выполненная работа: житель сообщил, УК выполнила, житель подтвердил.
    const resident = await auth(request, "a16-resident");
    // Заявка дома a1 сразу назначена ответственному: работу ведёт он.
    const admin = await auth(request, "a16-responsible");
    const created = await request.post("/api/v1/reports", {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { house_id: ids.house, category: "elevator", description: "Не работает лифт во втором подъезде" },
    });
    expect(created.status()).toBe(201);
    const incident = (await created.json()).incident.id;
    const tickets = await (await request.get(`/api/v1/tickets?house_id=${ids.house}`, { headers: admin })).json();
    const ticket = tickets.items.find((item: any) => item.incident_id === incident);
    let version = ticket.version;
    let attempt = "";
    for (const [action, body] of [["accept", {}], ["start", {}], ["work-attempts", { public_description: `Заменён блок управления лифтом. ${LONG_WORD}` }]] as const) {
      const response = await request.post(`/api/v1/tickets/${ticket.id}/${action}`, {
        headers: { ...admin, "Idempotency-Key": key() }, data: { expected_version: version, ...body },
      });
      expect(response.status()).toBe(200);
      const json = await response.json();
      version = json.ticket.version;
      attempt = json.attempt_id ?? attempt;
    }
    const observed = await request.post(`/api/v1/work-attempts/${attempt}/observations`, {
      headers: { ...resident, "Idempotency-Key": key() }, data: { outcome: "resolved" },
    });
    expect(observed.status()).toBe(200);

    const ctx = await context(browser, 390, 844);
    const page = await ctx.newPage();
    try {
      await page.goto(`/?test_actor=a16-resident&house=${ids.house}`);
      const nav = page.getByRole("navigation", { name: "Разделы" });
      await expect(nav).toBeVisible();
      await nav.getByRole("link", { name: "Мой дом" }).click();
      await expect(page.getByRole("heading", { name: "Мой дом", level: 1 })).toBeVisible();
      await expect(page.getByText("+7 843 000-00-02").first()).toBeVisible();
      await expect(page.getByText(/по данным (УК|управляющей компании)/i).first()).toBeVisible();
      // «Если авария» — первым блоком раздела.
      await expect(page.getByRole("heading", { name: "Если авария" })).toBeVisible();
      await noOverflow(page);
      await axeCheck(page);
      await page.emulateMedia({ colorScheme: "dark" });
      await axeCheck(page);
      await page.emulateMedia({ colorScheme: "light" });

      await nav.getByRole("link", { name: "Объявления" }).click();
      await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();
      await noOverflow(page);
      await axeCheck(page);
      await page.getByRole("button", { name: "Проголосовать" }).first().click();
      await expect(page.getByRole("heading", { name: QUESTION })).toBeVisible();
      await expect(page.getByText("Предварительный опрос. Не является решением общего собрания собственников.")).toBeVisible();
      await page.getByLabel(/Светло-серый/).check();
      await page.getByRole("button", { name: "Проголосовать" }).click();
      await expect(page.getByText(/Голос учтён/)).toBeVisible();
      await expect(page.getByText(/Проголосовали: 1/)).toBeVisible();
      await axeCheck(page);
      // «Назад» возвращает к объявлениям, откуда пришли.
      await page.getByRole("button", { name: /Назад/ }).click();
      await expect(page.getByRole("heading", { name: "Объявления", level: 1 })).toBeVisible();

      // Выполненные работы — внутри «Мой дом».
      await page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Мой дом" }).click();
      await page.getByRole("link", { name: "Что сделано в доме за последние месяцы" }).click();
      await expect(page.getByText("Жители подтвердили").first()).toBeVisible();
      await noOverflow(page);
      await axeCheck(page);
      await page.getByRole("list", { name: "Выполненные работы" }).getByRole("link").first().click();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.goBack();
      await expect(page.getByRole("heading", { name: "Что сделано в доме", level: 1 })).toBeVisible();

      await page.getByRole("button", { name: /Назад/ }).click();
      await page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Мои обращения" }).click();
      await expect(page.getByText("Ваше сообщение о проблеме").first()).toBeVisible();
      await noOverflow(page);
      await axeCheck(page);
    } finally { await ctx.close(); }
  });

  test("a foreign house and a staff member get honest refusals, not dead ends", async ({ browser }) => {
    const ctx = await context(browser, 390, 844);
    const page = await ctx.newPage();
    try {
      await page.goto(`/?test_actor=a16-outsider&house=${ids.house}&view=home`);
      await expect(page.getByRole("heading", { name: "Нет доступа к этому дому" })).toBeVisible();
      await expect(page.getByRole("button", { name: "К выбору дома" })).toBeVisible();
      await axeCheck(page);
      await page.goto(`/?test_actor=a16-admin&house=${ids.house}&view=home`);
      await expect(page.getByText("Раздел доступен жителям дома")).toBeVisible();
      // Не тупик: разделы и «Проблемы» на месте.
      await expect(page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Проблемы" })).toBeVisible();
      await noOverflow(page);
    } finally { await ctx.close(); }
  });
});
