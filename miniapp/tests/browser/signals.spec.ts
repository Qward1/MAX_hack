import { test, expect, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ACTOR = "p5-operator";

// Сигналы засеваются настоящим путём P4: события вебхука → приём → окно →
// разбор правилами (tests/browser/signal_fixture.py). Прямых INSERT нет.
function fixture(command: string) {
  const result = spawnSync("uv", ["run", "python", "tests/browser/signal_fixture.py", command], {
    cwd: "..",
    encoding: "utf8",
    env: process.env,
  });
  if (result.status !== 0) throw new Error(`Fixture ${command} failed: ${result.stderr}`);
  return JSON.parse(result.stdout.trim().split("\n").at(-1) ?? "{}");
}
async function axe(page: Page) {
  // CSP кабинета остаётся включённой: axe отдаётся тем же источником.
  await page.route("**/__test_axe.js", (route) =>
    route.fulfill({ path: require.resolve("axe-core/axe.min.js"), contentType: "text/javascript" }),
  );
  await page.addScriptTag({ url: "/__test_axe.js" });
  await page.unroute("**/__test_axe.js");
  const violations = await page.evaluate(async () =>
    (
      await (window as any).axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      })
    ).violations.map((v: any) => ({ id: v.id, targets: v.nodes.map((n: any) => n.target) })),
  );
  expect(violations).toEqual([]);
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}
async function openQueue(page: Page) {
  await page.goto(`/admin/?test_actor=${ACTOR}&section=signals`);
  await expect(page.getByRole("heading", { level: 1, name: "Сигналы" })).toBeVisible();
}
async function openSignal(page: Page, id: string, title: string) {
  await page.goto(`/admin/?test_actor=${ACTOR}&section=signals&signal=${id}`);
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
}

test.beforeAll(() => {
  fixture("prepare");
});
test.beforeEach(async ({ page }) => {
  await page.route("https://st.max.ru/**", (route) => route.abort());
});

test("P5-a thread of 7 lines → one card → create ticket → accepted in Tickets", async ({ page }) => {
  const { signal_id: id } = fixture("thread");
  await page.setViewportSize({ width: 1366, height: 900 });
  await openQueue(page);
  const nav = page.getByRole("navigation", { name: "Разделы кабинета" });
  await expect(nav.getByRole("link")).toHaveText(["Заявки", "Сигналы", "Мои дома", "Обзор", "Уведомления", "Приём"]);
  await expect(nav.getByRole("link", { name: "Сигналы" })).toHaveAttribute("aria-current", "page");
  // Правила дают слабый сигнал: он свёрнут в «Возможные (N)».
  const weak = page.getByRole("button", { name: /^Возможные \(\d+\)$/ });
  await expect(weak).toHaveAttribute("aria-expanded", "false");
  await weak.click();
  await expect(weak).toHaveAttribute("aria-expanded", "true");
  const cards = page.getByRole("link", { name: "Открыть сигнал: Лифт" });
  await expect(cards).toHaveCount(1);
  const card = page.locator("tr", { has: cards });
  await expect(card.getByText(/^7 реплик · \d жител/)).toBeVisible();
  await expect(card.getByText("Подъезд 2")).toBeVisible();
  await expect(card.getByText("УК", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/p5-queue-1366.png", fullPage: true });
  await noOverflow(page);
  await axe(page);

  await cards.click();
  await expect(page).toHaveURL(new RegExp(`signal=${id}`));
  await expect(page.getByRole("heading", { level: 1, name: "Лифт" })).toBeVisible();
  // Деталь открыта рядом с очередью; без признаков опасности первым идёт решение оператора.
  await expect(
    page.getByRole("region", { name: "Сигнал", exact: true }).getByRole("heading", { level: 2 }).first(),
  ).toHaveText("Действия по сигналу");
  await page.getByRole("button", { name: "Создать заявку" }).click();
  const form = page.getByRole("form", { name: "Создать заявку" });
  await expect(form.getByRole("combobox", { name: "Категория" })).toHaveValue("elevator");
  const description = form.getByRole("textbox", { name: "Описание заявки" });
  await expect(description).toHaveValue(/^Из домового чата: лифт\. Сообщений: 7/);
  await expect(description).toHaveValue(/«Лифт во втором подъезде опять не работает»/);
  await page.screenshot({ path: "test-results/p5-create-ticket-1366.png", fullPage: true });
  await axe(page);
  await form.getByRole("button", { name: "Создать заявку" }).click();
  await expect(page.getByText(/^Заявка T-\d+ создана и уже в разделе «Заявки»\.$/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Действия по сигналу" }).getByRole("button")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Заявка создана").first()).toBeVisible();
  const ticketLink = page.getByRole("link", { name: /^Открыть заявку T-\d+$/ });
  const number = ((await ticketLink.textContent()) ?? "").replace("Открыть заявку ", "");
  await ticketLink.click();
  await expect(page.getByRole("heading", { name: "Действия по заявке" })).toBeVisible();
  await expect(page.getByText(`Заявка ${number}`)).toBeVisible();
  await page.getByRole("button", { name: "Взять в работу" }).click();
  await expect(page.getByText("Действие сохранено. Показаны актуальные данные заявки.")).toBeVisible();
  // Та же заявка — в обычной очереди «Заявки».
  await page.getByRole("navigation", { name: "Разделы кабинета" }).getByRole("link", { name: "Заявки" }).click();
  await expect(page.getByRole("link", { name: `Открыть заявку ${number}` })).toBeVisible();
});

test("P5-b gas → critical banner, safety block first, emergency route before analysis", async ({
  page,
}) => {
  const { signal_id: id } = fixture("gas");
  for (const width of [1366, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await openQueue(page);
    const banner = page.getByRole("region", { name: /^Критические сигналы: \d+$/ });
    await expect(banner).toBeVisible();
    await expect(banner.getByText(/Последний — (сегодня|вчера|\d+ \S+), \d{2}:\d{2} МСК/)).toBeVisible();
    const critical = page.getByRole("link", { name: "Открыть сигнал: Признак опасности" }).first();
    await expect(page.locator("tr", { has: critical }).getByText("Критический")).toBeVisible();
    await expect(page.locator("tr", { has: critical }).getByText("Экстренные службы")).toBeVisible();
    await page.screenshot({ path: `test-results/p5-queue-critical-${width}.png`, fullPage: true });
    await noOverflow(page);
    await axe(page);
    await banner.getByRole("link", { name: "Открыть последний критический сигнал" }).click();
    await expect(page).toHaveURL(new RegExp(`signal=${id}`));
    const scope = width >= 1200 ? page.getByRole("region", { name: "Сигнал", exact: true }) : page.locator("main");
    const headings = scope.getByRole("heading", { level: 2 });
    await expect(headings.first()).toHaveText("Опасность: запах газа");
    await expect(page.getByText(/Переписку ещё разбирают/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Позвонить 112" })).toHaveAttribute("href", "tel:112");
    await expect(page.getByText("Маршрут: Экстренные службы", { exact: true })).toBeVisible();
    await expect(page.getByText(/Федеральный закон от 30\.12\.2020 № 488-ФЗ/).first()).toBeVisible();
    await page.screenshot({ path: `test-results/p5-gas-detail-${width}.png`, fullPage: true });
    await noOverflow(page);
    await axe(page);
  }
  // Back возвращает в очередь, reload детали — ту же деталь.
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "Сигналы" })).toBeVisible();
  await page.goForward();
  await page.reload();
  await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText("Опасность: запах газа");
});

test("P5-c close with a required reason", async ({ page }) => {
  const { signal_id: id } = fixture("light");
  await page.setViewportSize({ width: 390, height: 900 });
  await openSignal(page, id, "Освещение подъезда");
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  const form = page.getByRole("form", { name: "Закрыть" });
  const submit = form.getByRole("button", { name: "Закрыть сигнал" });
  await expect(submit).toBeDisabled();
  await form.getByRole("combobox", { name: "Причина" }).selectOption("not_a_problem");
  await form.getByRole("textbox", { name: "Комментарий (необязательно)" }).fill("Проверили: свет горит");
  await page.screenshot({ path: "test-results/p5-dismiss-390.png", fullPage: true });
  await noOverflow(page);
  await axe(page);
  await submit.click();
  await expect(page.getByText("Сигнал закрыт. Причина сохранена.")).toBeVisible();
  await page.reload();
  const history = page.getByRole("region", { name: "История решения" });
  await expect(history.getByText("Не проблема")).toBeVisible();
  await expect(history.getByText("Проверили: свет горит")).toBeVisible();
  await expect(history.getByText("Оператор П5").first()).toBeVisible();
  await expect(history.getByText("Оператор закрыл сигнал")).toBeVisible();
});

test("P5-d unknown route → operator chooses → external route without sending", async ({ page }) => {
  const { signal_id: id } = fixture("playground");
  await page.setViewportSize({ width: 1366, height: 900 });
  await openSignal(page, id, "Детская площадка");
  await expect(page.getByText("Маршрут: Не определён", { exact: true })).toBeVisible();
  const external = page.getByRole("button", { name: "Отметить внешний маршрут" });
  await expect(external).toBeDisabled();
  const reason = await external.getAttribute("aria-describedby");
  expect(reason).toBeTruthy();
  await expect(page.locator(`#${reason}`)).toContainText("Сначала выберите маршрут");
  await page.getByRole("button", { name: "Выбрать маршрут" }).click();
  const form = page.getByRole("form", { name: "Выбрать маршрут" });
  await expect(form.getByRole("combobox", { name: "Маршрут" }).getByRole("option")).toHaveText([
    "Выберите маршрут",
    "Управляющая компания дома",
    "Муниципалитет",
  ]);
  await form.getByRole("combobox", { name: "Маршрут" }).selectOption("municipality");
  await page.screenshot({ path: "test-results/p5-choose-route-1366.png", fullPage: true });
  await axe(page);
  await form.getByRole("button", { name: "Выбрать маршрут" }).click();
  await expect(page.getByText("Маршрут выбран. Теперь примите решение по сигналу.")).toBeVisible();
  await expect(page.getByText("Маршрут: Муниципалитет", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Маршрут выбран оператором Оператор П5/)).toBeVisible();
  await page.getByRole("button", { name: "Отметить внешний маршрут" }).click();
  const confirm = page.getByRole("form", { name: "Отметить внешний маршрут" });
  await expect(confirm.getByText(/ДомСигнал никуда ничего не отправляет/)).toBeVisible();
  await confirm.getByRole("button", { name: "Отметить внешний маршрут" }).click();
  await expect(page.getByText("Отмечен внешний маршрут. ДомСигнал никуда ничего не отправлял.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 900 });
  await page.reload();
  const history = page.getByRole("region", { name: "История решения" });
  await expect(history.getByText("Внешний маршрут", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/p5-routed-external-390.png", fullPage: true });
  await noOverflow(page);
  await axe(page);
});
