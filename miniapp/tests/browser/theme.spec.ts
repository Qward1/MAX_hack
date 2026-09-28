import { expect, test, type Browser, type Page } from "@playwright/test";

// Переключатель темы (F2): на каждой поверхности, выбор сильнее темы системы и
// сохраняется после перезагрузки (ставится до первой отрисовки — theme-init.js).
// Стенд — как у F1: HTTP + PostgreSQL с тестовыми входами (miniapp/README.md).
async function context(browser: Browser, width = 1280) {
  const ctx = await browser.newContext({
    colorScheme: "light",
    viewport: { width, height: width < 500 ? 844 : 800 },
    reducedMotion: "reduce",
  });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", (route) => route.abort());
  return ctx;
}
const background = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

const SURFACES: [string, string][] = [
  ["сайт", "/site"],
  ["вход", "/login"],
  ["заявка УК", "/company/apply"],
  ["политика данных", "/privacy"],
  ["житель", "/?test_actor=a16-resident"],
  ["кабинет УК", "/admin/?test_actor=a16-admin"],
];

test.describe("theme toggle", () => {
  test.skip(process.env.APP_ENV !== "test", "Needs the HTTP/PostgreSQL stand with test sessions");

  for (const [name, path] of SURFACES) {
    test(`${name}: тёмная тема по кнопке и после перезагрузки`, async ({ browser }) => {
      const ctx = await context(browser);
      const page = await ctx.newPage();
      try {
        await page.goto(path);
        const toDark = page.getByRole("button", { name: "Включить тёмную тему" }).first();
        await expect(toDark).toBeVisible();
        const light = await background(page);
        await toDark.click();
        await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
        await expect.poll(() => background(page)).not.toBe(light);
        await page.reload();
        await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
        await expect(page.getByRole("button", { name: "Включить светлую тему" }).first()).toBeVisible();
        await page.getByRole("button", { name: "Включить светлую тему" }).first().click();
        await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
        await expect.poll(() => background(page)).toBe(light);
      } finally {
        await ctx.close();
      }
    });
  }

  test("выбор общий для поверхностей: сайт → вход", async ({ browser }) => {
    const ctx = await context(browser);
    const page = await ctx.newPage();
    try {
      await page.goto("/site");
      await page.getByRole("button", { name: "Включить тёмную тему" }).click();
      await page.goto("/login");
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    } finally {
      await ctx.close();
    }
  });

  test("кабинет УК на телефоне: тема — в листе «Разделы», шапка в одну строку", async ({ browser }) => {
    const ctx = await context(browser, 320);
    const page = await ctx.newPage();
    try {
      await page.goto("/admin/?test_actor=a16-admin");
      const bar = page.locator(".admin-mobile-bar");
      await expect(bar).toBeVisible();
      const heights = await bar.evaluate((el) =>
        [...el.children].map((child) => child.getBoundingClientRect().top),
      );
      expect(new Set(heights.map(Math.round)).size).toBe(1);
      await page.getByRole("button", { name: "Разделы" }).click();
      await page.getByRole("button", { name: "Включить тёмную тему" }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    } finally {
      await ctx.close();
    }
  });
});
