import { test, expect, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";

function fixture(command: string, arg?: string) {
  const r = spawnSync("uv", ["run", "python", "tests/browser/administration_fixture.py", command, ...(arg ? [arg] : [])],
    { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout);
}
function otp() {
  const r = spawnSync("uv", ["run", "python", "tests/browser/employee_fixture.py", "otp"],
    { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout).code;
}
async function enrollment(page: Page) {
  await page.getByRole("button", { name: "Показать QR-код" }).click();
  await expect(page.getByAltText("QR-код для подключения аутентификатора")).toBeVisible();
  await page.getByLabel("Код из приложения").fill(otp());
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByRole("heading", { name: "Сохраните коды восстановления" })).toBeVisible();
  await page.getByRole("button", { name: "Коды сохранены — открыть кабинет" }).click();
}
async function acceptNew(page: Page, link: string, login: string) {
  // API public origin uses loopback HTTP for this fixture; use the same running browser origin.
  await page.goto(new URL(link).pathname);
  await page.getByLabel("Ваше имя").fill(login);
  await page.getByLabel("Логин", { exact: true }).fill(login);
  await page.getByLabel("Пароль", { exact: true }).fill("B09 unique employee password 852!");
  await page.getByRole("button", { name: "Создать аккаунт и настроить MFA" }).click();
  expect((await page.context().request.get("/api/v1/admin/bootstrap")).status()).toBe(401);
  await enrollment(page);
}

test("B09 full administrative lifecycle, separate surfaces, privacy and revoke", async ({ browser, request }) => {
  test.skip(process.env.B09_BROWSER_FIXTURES !== "1", "Needs isolated HTTP/PostgreSQL fixtures");
  test.setTimeout(150000);
  const suffix = Date.now().toString().slice(-7);
  const companyName = `B09 УК ${suffix}`;
  const address = `B09 новый дом ${suffix}, 10`;
  const platformSetup = fixture("platform");
  const publicContext = await browser.newContext();
  const platformContext = await browser.newContext();
  const adminContext = await browser.newContext();
  const operatorContext = await browser.newContext();
  for (const context of [publicContext, platformContext, adminContext, operatorContext]) context.setDefaultTimeout(10000);
  try {
    const applicant = await publicContext.newPage();
    await applicant.goto("/company/apply");
    await applicant.getByLabel("Полное наименование").fill(`ООО ${companyName}`);
    await applicant.getByLabel("Краткое наименование").fill(companyName);
    await applicant.getByLabel("ИНН", { exact: true }).fill(`770${suffix}`);
    await applicant.getByLabel("Контактное лицо").fill("B09 Test applicant");
    await applicant.getByLabel("Электронная почта").fill("b09@example.test");
    await applicant.getByRole("button", { name: "Подать заявку" }).click();
    await expect(applicant.getByRole("heading", { name: "Данные получены" })).toBeVisible();
    expect((await publicContext.request.get("/api/v1/admin/bootstrap")).status()).toBe(401);

    const platform = await platformContext.newPage();
    await platform.goto("/platform-admin/");
    await platform.getByLabel("Логин").fill("b09.platform");
    await platform.getByLabel("Пароль", { exact: true }).fill(platformSetup.password);
    await platform.getByRole("button", { name: "Войти", exact: true }).click();
    await platform.getByLabel("Новый пароль").fill("B09 unique platform password 593!");
    await platform.getByRole("button", { name: "Продолжить" }).click();
    await enrollment(platform);
    await expect(platform.getByRole("navigation", { name: "Разделы платформы" })).toBeVisible();
    await expect(platform.locator(".ticket-queue")).toHaveCount(0);
    await platform.getByRole("button", { name: `ООО ${companyName}`, exact: true }).click();
    await platform.getByLabel("Основание решения / сообщение для заявителя").fill("B09 deterministic review");
    await platform.getByRole("button", { name: "Одобрить УК", exact: true }).click();
    const firstLink = await platform.getByLabel("Одноразовая ссылка").inputValue();
    expect(firstLink).toContain("/admin/invite/");

    const admin = await adminContext.newPage();
    const adminLogin = `b09.admin.${suffix}`;
    await acceptNew(admin, firstLink, adminLogin);
    await expect(admin.getByRole("heading", { name: "Обзор", exact: true })).toBeVisible();
    const companyNav = admin.getByRole("navigation", { name: "Разделы кабинета" });
    await expect(companyNav.getByRole("link")).toHaveCount(6);
    await companyNav.getByRole("link", { name: "Сотрудники", exact: true }).click();
    await admin.getByRole("button", { name: "Пригласить сотрудника", exact: true }).click();
    const operatorLink = await admin.getByLabel("Одноразовая ссылка").inputValue();
    const operator = await operatorContext.newPage();
    const operatorLogin = `b09.operator.${suffix}`;
    await acceptNew(operator, operatorLink, operatorLogin);
    await expect(operator.getByRole("heading", { name: "Заявки", exact: true })).toBeVisible();
    await expect(operator.getByRole("navigation", { name: "Разделы кабинета" }).getByRole("link")).toHaveText(["Заявки", "Мои дома"]);

    await companyNav.getByRole("link", { name: "Дома", exact: true }).click();
    await admin.getByRole("button", { name: "Запросить управление домом" }).click();
    await admin.getByLabel("Адрес", { exact: true }).fill(address);
    await admin.getByLabel("Основание и комментарий").fill("B09 isolated management agreement");
    await admin.getByRole("button", { name: "Подать заявку на управление" }).click();
    await expect(admin.getByRole("heading", { name: address, exact: true })).toBeVisible();
    await platform.getByRole("link", { name: "Заявки на дома", exact: true }).click();
    await platform.getByRole("button", { name: address, exact: true }).click();
    await platform.getByLabel("Решение о доме").selectOption("new");
    await platform.getByLabel("Основание решения / уточнения").fill("B09 explicit new physical house");
    await platform.getByRole("button", { name: "Одобрить управление" }).click();
    await expect(platform.getByRole("button", { name: "Одобрить управление" })).toHaveCount(0);

    await companyNav.getByRole("link", { name: "Сотрудники", exact: true }).click();
    await admin.getByRole("button", { name: operatorLogin, exact: true }).click();
    await admin.getByLabel(`Доступ: ${address}`).selectOption("operator");
    await expect(admin.getByLabel(`Доступ: ${address}`)).toHaveValue("operator");
    await operator.reload();
    await operator.getByRole("link", { name: "Мои дома", exact: true }).click();
    await expect(operator.getByRole("heading", { name: address, exact: true })).toBeVisible();
    await expect(operator.getByRole("button", { name: /Подключить.*MAX/ })).toHaveCount(0);
    await operator.reload();
    await expect(operator.getByRole("heading", { name: address, exact: true })).toBeVisible();

    await companyNav.getByRole("link", { name: "MAX-чаты", exact: true }).click();
    await admin.getByRole("button", { name: "Подключить существующий MAX-чат" }).click();
    const command = await admin.getByLabel("Команда подключения MAX").inputValue();
    fixture("connect", command.replace("/start ", ""));
    await admin.getByRole("button", { name: "Обновить", exact: true }).click();
    await admin.getByRole("button", { name: "Подтвердить подключение", exact: true }).click();
    await expect(admin.getByText("Synthetic chat")).toBeVisible();

    // Real private marker in an existing resident report, then all platform read projections and rendering.
    const resident = await request.post("/api/v1/auth/test-session", { data: { actor: "a16-resident" } });
    const residentHeaders = { Authorization: `Bearer ${(await resident.json()).access_token}`, "Idempotency-Key": crypto.randomUUID() };
    const residentScope = fixture("resident", address);
    const marker = `PLATFORM_PRIVATE_MARKER_${suffix}`;
    expect((await request.post("/api/v1/reports", { headers: residentHeaders, data: { house_id: residentScope.house_id, category: "water", description: marker } })).status()).toBe(201);
    await operator.getByRole("link", { name: "Заявки", exact: true }).click();
    const operatorTicket = operator.getByRole("link", { name: /^Открыть заявку T-/ });
    await expect(operatorTicket).toHaveCount(1);
    await operatorTicket.click();
    await operator.getByRole("button", { name: "Взять в работу", exact: true }).click();
    await operator.getByRole("button", { name: "Начать работу", exact: true }).click();
    await operator.getByRole("button", { name: "Сообщить о выполнении", exact: true }).click();
    const dialog = operator.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Что было сделано?" }).fill("B09 historical work survives revocation");
    await dialog.getByRole("button", { name: "Сообщить о выполнении" }).click();
    await expect(dialog).toHaveCount(0);
    for (const section of ["Заявки УК", "Организации", "Заявки на дома", "Дома", "Спорные MAX-привязки", "Состояние системы", "Аудит"]) {
      await platform.getByRole("navigation", { name: "Разделы платформы" }).getByRole("link", { name: section, exact: true }).click();
      await expect(platform.getByRole("heading", { name: section, exact: true })).toBeVisible();
      await expect(platform.getByText(marker)).toHaveCount(0);
    }
    // Chrome accepts Secure cookies on loopback; Playwright's Node request client does not.
    expect(await admin.evaluate(async () => (await fetch("/api/v1/platform/bootstrap")).status)).toBe(403);
    await companyNav.getByRole("link", { name: "Сотрудники", exact: true }).click();
    await admin.getByRole("button", { name: operatorLogin, exact: true }).click();
    await admin.getByRole("button", { name: "Отозвать доступ сотрудника", exact: true }).click();
    await admin.getByRole("button", { name: "Подтвердить отзыв", exact: true }).click();
    await operator.reload();
    await expect(operator.getByText(address, { exact: true })).toHaveCount(0);
    await expect(operator.getByText("Активных назначений нет.", { exact: false })).toBeVisible();
    await companyNav.getByRole("link", { name: "Заявки", exact: true }).click();
    const companyTicket = admin.getByRole("link", { name: /^Открыть заявку T-/ });
    await expect(companyTicket).toHaveCount(1);
    await companyTicket.click();
    await expect(admin.getByText("B09 historical work survives revocation", { exact: true })).toBeVisible();
    await applicant.goto("/?test_actor=a16-resident");
    await expect(applicant.locator(".admin-sidebar")).toHaveCount(0);
    await platform.screenshot({ path: "test-results/b09-platform.png", fullPage: true });
    await admin.screenshot({ path: "test-results/b09-company.png", fullPage: true });
  } finally { await Promise.all([publicContext.close(), platformContext.close(), adminContext.close(), operatorContext.close()]); }
});
