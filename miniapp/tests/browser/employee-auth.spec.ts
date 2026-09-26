import { test, expect } from "@playwright/test";
import { spawnSync } from "node:child_process";

function fixture(command: string) {
  const result = spawnSync("uv", ["run", "python", "tests/browser/employee_fixture.py", command], {
    cwd: "..", encoding: "utf8", env: process.env,
  });
  if (result.status !== 0) throw new Error(`Employee fixture failed: ${result.stderr}`);
  return JSON.parse(result.stdout);
}

test("employee cookie flow, reload, real queue, logout and cross-user cache isolation", async ({ page, context, request }) => {
  test.setTimeout(60000);
  const setup = fixture("setup");
  const resident = await request.post("/api/v1/auth/test-session", { data: { actor: "a16-resident" } });
  const report = await request.post("/api/v1/reports", {
    headers: { Authorization: `Bearer ${(await resident.json()).access_token}`, "Idempotency-Key": crypto.randomUUID() },
    data: { house_id: setup.house, category: "water", description: `Auth browser report ${crypto.randomUUID()}` },
  });
  expect(report.status()).toBe(201);
  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Вход сотрудника" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Заявки", exact: true })).toHaveCount(0);
  await page.getByLabel("Логин").fill("BROWSER.Employee");
  await page.getByLabel("Пароль", { exact: true }).fill(setup.password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Создайте свой пароль" })).toBeVisible();
  await page.getByLabel("Новый пароль").fill("Unique browser passphrase 73985!");
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("button", { name: "Показать QR-код" }).click();
  await expect(page.getByAltText("QR-код для подключения аутентификатора")).toBeVisible();
  expect((await context.request.get("/api/v1/me")).status()).toBe(401);
  await page.getByLabel("Код из приложения").fill(fixture("otp").code);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByRole("heading", { name: "Сохраните коды восстановления" })).toBeVisible();
  const codes = await page.locator(".recovery-codes code").allTextContents();
  expect(codes).toHaveLength(10);
  await page.getByRole("button", { name: "Коды сохранены — открыть кабинет" }).click();
  await page.getByRole("navigation", { name: "Разделы кабинета" }).getByRole("link", { name: "Заявки", exact: true }).click();
  await expect(page.locator(".queue-table tbody tr").first()).toBeVisible();
  const cookies = await context.cookies();
  const cookie = cookies.find(c => c.name === "__Host-domsignal_employee")!;
  expect(cookie).toMatchObject({ secure: true, httpOnly: true, sameSite: "Lax", path: "/" });
  const session = await (await context.request.get("/api/v1/auth/employee/session")).json();
  await page.reload();
  await expect(page.locator(".queue-table tbody tr").first()).toBeVisible();
  expect((await context.cookies()).find(c => c.name === cookie.name)?.value).toBe(cookie.value);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.locator(".queue-table .cell-main a").first().click();
  await expect(page.locator(".ticket-detail, .ticket-panel").first()).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Вход сотрудника" })).toBeVisible();
  await expect(page.locator(".queue-table tbody tr, .decision-panel")).toHaveCount(0);
  expect((await request.get("/api/v1/me", { headers: { Cookie: `${cookie.name}=${cookie.value}` } })).status()).toBe(401);
  // Back navigation cannot reveal cached private UI; switch to a new authenticated session.
  await page.goBack();
  await expect(page.locator(".queue-table tbody tr, .decision-panel")).toHaveCount(0);
  await page.goto("/admin/login");
  await page.getByLabel("Логин").fill("browser.employee");
  await page.getByLabel("Пароль", { exact: true }).fill("Unique browser passphrase 73985!");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("button", { name: "Использовать код восстановления" }).click();
  await page.getByLabel("Код восстановления").fill(codes[0]);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("navigation", { name: "Разделы кабинета" }).getByRole("link", { name: "Заявки", exact: true }).click();
  await expect(page.locator(".queue-table tbody tr").first()).toBeVisible();
  expect(session.csrf_token).toBeTruthy();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  const beta = fixture("setup-beta");
  await page.getByLabel("Логин").fill("browser.beta");
  await page.getByLabel("Пароль", { exact: true }).fill(beta.password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByLabel("Новый пароль").fill("Different company password 39524!");
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("button", { name: "Показать QR-код" }).click();
  await expect(page.getByAltText("QR-код для подключения аутентификатора")).toBeVisible();
  await page.getByLabel("Код из приложения").fill(fixture("otp").code);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("button", { name: "Коды сохранены — открыть кабинет" }).click();
  await page.getByRole("navigation", { name: "Разделы кабинета" }).getByRole("link", { name: "Заявки", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Заявки", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A16 synthetic house b1", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A16 synthetic house a1", exact: true })).toHaveCount(0);
  await expect(page.locator(".queue-table tbody tr")).toHaveCount(0);
});
