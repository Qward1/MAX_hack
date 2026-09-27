import { expect, test, type Browser, type Page } from "@playwright/test";
import { createRequire } from "node:module";

// Повторный UI/UX-аудит 27.09.2026 (RA-01…RA-08): то, что видно только в
// настоящем браузере, — первый экран 320 × 640, закреплённое закрытие листа,
// клавиатура и возврат фокуса, заголовки вкладок, одна цель звонка 112.
// Стенд — как у UX-D3: HTTP + PostgreSQL с seed_demo и seed_tickets.
const require = createRequire(import.meta.url);
const DEMO_HOUSE = "00000000-0000-0000-0000-000000000101";

async function context(browser: Browser, width: number, height: number) {
  const ctx = await browser.newContext({ viewport: { width, height }, bypassCSP: true, reducedMotion: "reduce" });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", (route) => route.abort());
  return ctx;
}
const box = async (page: Page, selector: string) => (await page.locator(selector).first().boundingBox())!;
const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

async function axe(page: Page, name: string) {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () =>
    (
      await (window as unknown as { axe: { run: (...a: unknown[]) => Promise<{ violations: { id: string }[] }> } }).axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"] },
      })
    ).violations.map((v) => v.id),
  );
  expect(violations, `${name}: axe`).toEqual([]);
}

test("RA-01/RA-08 заявка УК: первое поле в первом экране 320 × 640, на компьютере две колонки", async ({ browser }) => {
  const phone = await context(browser, 320, 640);
  try {
    const page = await phone.newPage();
    await page.goto("/company/apply");
    await expect(page).toHaveTitle("Подключить УК · ДомСигнал");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const field = await box(page, "#apply-legal_name");
    expect(field.y + field.height, "первое поле целиком в первом экране").toBeLessThanOrEqual(640);
    expect(await noOverflow(page)).toBe(true);
    await page.getByRole("link", { name: "Перейти к заявке" }).click();
    await expect(page).toHaveURL(/#company-application$/);
    // Заголовок формы у верхнего края (с учётом общего scroll-padding), первое поле — на экране.
    const heading = await box(page, "#company-application-title");
    expect(heading.y).toBeGreaterThanOrEqual(0);
    expect(heading.y).toBeLessThan(160);
    await expect(page.locator("#apply-legal_name")).toBeInViewport();
    // Подробности и правила — после формы, но на месте.
    await expect(page.getByText("Как проходит подключение")).toBeAttached();
    await expect(page.getByRole("link", { name: "Политика данных" })).toBeAttached();
    await axe(page, "apply-320");
  } finally { await phone.close(); }
  const desktop = await context(browser, 1280, 800);
  try {
    const page = await desktop.newPage();
    await page.goto("/company/apply");
    await expect(page.getByRole("link", { name: "Перейти к заявке" })).toBeHidden();
    const intro = await box(page, ".apply-intro");
    const card = await box(page, ".apply-card");
    const more = await box(page, ".apply-more");
    expect(card.x, "форма — правая колонка").toBeGreaterThan(intro.x + intro.width);
    expect(more.x, "подробности — под вступлением слева").toBeLessThan(card.x);
    expect(more.y).toBeGreaterThan(intro.y);
  } finally { await desktop.close(); }
});

test("RA-08 у страниц кабинета и платформы свои заголовки вкладок", async ({ page }) => {
  await page.goto("/platform-admin/");
  await expect(page).toHaveTitle("Управление платформой · ДомСигнал");
  await page.goto("/admin/");
  await expect(page).toHaveTitle("Кабинет УК · ДомСигнал");
  await page.goto("/login");
  await expect(page).toHaveTitle("Вход · ДомСигнал");
});

test("RA-03 меню кабинета на 320 × 640: подпись в одну строку, закрытие всегда видно, клавиатура", async ({ browser }) => {
  const ctx = await context(browser, 320, 640);
  try {
    const page = await ctx.newPage();
    await page.goto("/admin/?test_actor=a16-admin");
    const menu = page.getByRole("button", { name: "Разделы" });
    await expect(menu).toBeVisible();
    expect((await menu.boundingBox())!.height, "подпись «Разделы» в одну строку").toBeLessThanOrEqual(48);
    await menu.click();
    const sheet = page.locator("dialog[open]");
    const close = sheet.getByRole("button", { name: "Закрыть" });
    const inView = async () => {
      const b = (await close.boundingBox())!;
      return b.y >= 0 && b.y + b.height <= 640;
    };
    expect(await inView()).toBe(true);
    // Длинный список прокручивается под закреплённой шапкой.
    await sheet.evaluate((d) => { d.scrollTop = d.scrollHeight; });
    expect(await inView(), "закрытие после прокрутки списка").toBe(true);
    await expect(sheet.getByRole("link", { name: "Приём" })).toBeInViewport();
    await axe(page, "admin-menu-320");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(menu).toBeFocused();
    await menu.press("Enter");
    await expect(page.locator("dialog[open]")).toBeVisible();
    await page.locator("dialog[open]").getByRole("button", { name: "Закрыть" }).click();
    await expect(page.locator("dialog[open]")).toHaveCount(0);
    await expect(menu).toBeFocused();
    expect(await noOverflow(page)).toBe(true);
  } finally { await ctx.close(); }
});

test("RA-02 пустой график на компьютере не растягивается до соседнего", async ({ browser }) => {
  const ctx = await context(browser, 1280, 800);
  try {
    const page = await ctx.newPage();
    await page.goto("/admin/?test_actor=a16-admin");
    await expect(page.getByRole("heading", { level: 2, name: "По домам" })).toBeVisible();
    const empty = page.locator(".chart-grid-2 > .chart-empty-row");
    test.skip(!(await empty.count()), "на стенде оба графика с данными или оба пустые");
    const card = (await empty.boundingBox())!;
    const chart = (await page.locator(".chart-grid-2 > figure.chart").boundingBox())!;
    expect(card.height).toBeLessThan(chart.height / 2);
    expect(chart.width, "график с данными шире пустой карточки").toBeGreaterThan(card.width);
  } finally { await ctx.close(); }
});

test("RA-05 «Если авария»: у номера 112 одна цель звонка", async ({ browser }) => {
  const ctx = await context(browser, 390, 844);
  try {
    const page = await ctx.newPage();
    await page.goto(`/?test_actor=demo&house=${DEMO_HOUSE}&view=home`);
    const emergency = page.locator("#emergency");
    await expect(emergency.getByRole("link", { name: "Позвонить 112" })).toHaveAttribute("href", "tel:112");
    await expect(emergency.locator('a[href="tel:112"]')).toHaveCount(1);
  } finally { await ctx.close(); }
});
