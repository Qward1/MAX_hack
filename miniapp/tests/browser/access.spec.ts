import { expect, test, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

// D1 §4: вход без тупиков — путь через кнопку домового чата, открытый дом и
// пропажа доступа. Данные — синтетический дом seed_demo; переключатель
// открытого доступа двигает та же служба, что и кабинет УК.
const require = createRequire(import.meta.url);

function fixture(command: "guest" | "open" | "close") {
  const result = spawnSync("uv", ["run", "python", "tests/browser/d1_fixture.py", command], {
    cwd: "..",
    encoding: "utf8",
    env: process.env,
  });
  if (result.status !== 0) throw new Error(result.stderr);
  return JSON.parse(result.stdout) as { address?: string };
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
}

async function axeCheck(page: Page) {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () =>
    (
      await (window as any).axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      })
    ).violations.map((v: any) => ({ id: v.id, targets: v.nodes.map((n: any) => n.target) })),
  );
  expect(violations).toEqual([]);
}

const CHAT_PATH = "Откройте ДомСигнал кнопкой из вашего домового чата.";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  test.skip(process.env.B14_BROWSER_FIXTURES !== "1", "Needs isolated HTTP/PostgreSQL fixtures");
  await page.route("https://st.max.ru/**", (route) => route.abort());
});

test.afterAll(() => {
  if (process.env.B14_BROWSER_FIXTURES === "1") fixture("close");
});

test("D1: без дома — понятный путь через кнопку чата, открытых домов нет", async ({ page }) => {
  fixture("close");
  fixture("guest");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?test_actor=d1-guest");
  await expect(page.getByText("Загружаем проблемы дома")).toHaveCount(0, { timeout: 10000 });
  await expect(page.getByRole("heading", { name: "Как открыть свой дом" })).toBeVisible();
  await expect(page.getByText(CHAT_PATH)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Дома с открытым доступом" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Проверить снова" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/тестов|демо-доступ/i);
  await noOverflow(page);
  await axeCheck(page);
});

test("D1: открытый дом — выбрать, увидеть доску; выключили — доступ пропал", async ({ page }) => {
  fixture("guest");
  const { address } = fixture("open");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?test_actor=d1-guest");
  await expect(page.getByRole("heading", { name: "Дома с открытым доступом" })).toBeVisible();
  await expect(page.getByText(CHAT_PATH)).toBeVisible();
  await noOverflow(page);
  await axeCheck(page);
  await page.getByRole("button", { name: `Выбрать дом: ${address}` }).click();
  await expect(page.getByRole("heading", { name: "Проблемы дома", level: 1 })).toBeVisible();
  await expect(page.getByText(address, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Сообщить о проблеме", exact: true })).toBeVisible();
  const houseUrl = page.url();
  expect(new URL(houseUrl).searchParams.get("house")).toBeTruthy();

  // Управляющая компания выключила открытый доступ: доска закрыта, путь назад есть.
  fixture("close");
  await page.goto(houseUrl);
  await expect(page.getByRole("heading", { name: "Нет доступа к этому дому" })).toBeVisible();
  await expect(
    page.getByText(/Откройте ДомСигнал кнопкой из вашего домового чата или выберите другой дом/),
  ).toBeVisible();
  await page.getByRole("button", { name: "К выбору дома" }).click();
  await expect(page.getByRole("heading", { name: "Как открыть свой дом" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Дома с открытым доступом" })).toHaveCount(0);
  await noOverflow(page);
});

test("D1: дом закрыли, пока житель выбирал, — человеческая ошибка", async ({ page }) => {
  fixture("guest");
  const { address } = fixture("open");
  await page.goto("/?test_actor=d1-guest");
  await expect(page.getByRole("button", { name: `Выбрать дом: ${address}` })).toBeVisible();
  fixture("close");
  await page.getByRole("button", { name: `Выбрать дом: ${address}` }).click();
  await expect(page.getByRole("alert")).toHaveText("Этот дом больше нельзя выбрать. Обновите список.");
  await page.getByRole("button", { name: "Проверить снова" }).click();
  await expect(page.getByRole("heading", { name: "Дома с открытым доступом" })).toHaveCount(0);
});
