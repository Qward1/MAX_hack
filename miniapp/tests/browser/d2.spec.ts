import { expect, test, type Browser, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

// D2: публичная страница, единый вход, заявка УК со страницей статуса, квота
// чатов с запросом расширения, сброс пароля/MFA и открытая регистрация.
const require = createRequire(import.meta.url);
const PASSWORD = "D2 unique employee password 4815!";

function run(script: string, args: string[]) {
  const r = spawnSync("uv", ["run", "python", script, ...args], { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout);
}
const d2 = (...args: string[]) => run("tests/browser/d2_fixture.py", args);
const enrollOtp = () => run("tests/browser/employee_fixture.py", ["otp"]).code as string;

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
async function enrollment(page: Page) {
  await page.getByRole("button", { name: "Показать QR-код" }).click();
  await expect(page.getByAltText("QR-код для подключения аутентификатора")).toBeVisible();
  await page.getByLabel("Код из приложения").fill(enrollOtp());
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByRole("heading", { name: "Сохраните коды восстановления" })).toBeVisible();
  await page.getByRole("button", { name: "Коды сохранены — открыть кабинет" }).click();
}
async function context(browser: Browser, width = 1280) {
  // bypassCSP — только чтобы подключить axe для проверки доступности.
  // reducedMotion — axe не должен мерить контраст посреди появления примера.
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, bypassCSP: true, reducedMotion: "reduce" });
  ctx.setDefaultTimeout(15000);
  // Внешние скрипты MAX стенду не нужны и в проверках не участвуют.
  await ctx.route("https://st.max.ru/**", route => route.abort());
  return ctx;
}

test("D2 site: landing, login entry and application page in a regular browser", async ({ browser }) => {
  const ctx = await context(browser, 390);
  const page = await ctx.newPage();
  try {
    await page.goto("/site");
    await expect(page.getByRole("heading", { level: 1, name: "Проблемы дома — из домового чата в работу" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Подключить УК" }).first()).toHaveAttribute("href", "/company/apply");
    await expect(page.getByRole("link", { name: "Вход", exact: true })).toHaveAttribute("href", "/login");
    await expect(page.getByRole("heading", { name: "Как это работает" })).toBeVisible();
    await expect(page.getByText("Пример: как переписка становится сигналом и заявкой")).toBeVisible();
    await noOverflow(page);
    await axeCheck(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await axeCheck(page);
    await page.getByRole("link", { name: "Вход", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Вход в кабинет" })).toBeVisible();
    await noOverflow(page);
    await page.goto("/company/apply");
    await expect(page.getByLabel("Сколько домовых чатов хотите подключить")).toBeVisible();
    await expect(page.getByRole("link", { name: "Вход", exact: true })).toHaveAttribute("href", "/login");
    await noOverflow(page);
    await page.goto("/company/apply/status/" + "x".repeat(43));
    await expect(page.getByRole("alert")).toContainText("не найдена");
  } finally { await ctx.close(); }
});

test("D2 onboarding: status page, quota, expansion, reset and open registration", async ({ browser }) => {
  test.skip(process.env.D2_BROWSER_FIXTURES !== "1", "Needs isolated HTTP/PostgreSQL D2 fixtures");
  test.setTimeout(300000);
  const suffix = Date.now().toString().slice(-8);
  const inn = `77${suffix}`;
  const company = `УК Проверка ${suffix}`;
  const adminLogin = `d2.admin.${suffix}`;
  d2("reset-rate");
  const platformSetup = d2("platform");
  const applicantCtx = await context(browser, 390);
  const platformCtx = await context(browser);
  const adminCtx = await context(browser);
  const operatorCtx = await context(browser);
  const joinCtx = await context(browser);
  try {
    // 1. Заявка УК и страница статуса по секретной ссылке.
    const applicant = await applicantCtx.newPage();
    await applicant.goto("/company/apply");
    await applicant.getByLabel("Полное наименование").fill(`ООО ${company}`);
    await applicant.getByLabel("Краткое наименование").fill(company);
    await applicant.getByLabel("ИНН", { exact: true }).fill(inn);
    await applicant.getByLabel("Сколько домовых чатов хотите подключить").fill("2");
    await applicant.getByLabel("Адреса домов").fill(`Казань, ул. Проверочная, ${suffix.slice(-2)}`);
    await applicant.getByLabel("Контактное лицо").fill("Контактное лицо D2");
    await applicant.getByLabel("Электронная почта").fill("d2@example.test");
    await applicant.getByRole("button", { name: "Подать заявку" }).click();
    await expect(applicant.getByRole("heading", { name: "Заявка принята" })).toBeVisible();
    await applicant.getByRole("link", { name: "Открыть страницу статуса" }).click();
    await expect(applicant.getByRole("heading", { name: "Заявка получена" })).toBeVisible();
    const statusUrl = applicant.url();
    expect(statusUrl).toMatch(/\/company\/apply\/status\/[A-Za-z0-9_-]{43}$/);
    await noOverflow(applicant);
    await axeCheck(applicant);
    await applicant.getByRole("button", { name: "Получать уведомления в MAX" }).click();
    await expect(applicant.getByRole("link", { name: "Открыть бота в MAX" })).toHaveAttribute("href", /^https:\/\/max\.ru\/[A-Za-z0-9_]+\?start=ca_[A-Za-z0-9_-]{32}$/);

    // 2. Суперадмин входит через единый вход и попадает в обзор платформы.
    const platform = await platformCtx.newPage();
    await platform.goto("/login");
    await platform.getByLabel("Логин").fill("d2.platform");
    await platform.getByLabel("Пароль", { exact: true }).fill(platformSetup.password);
    await platform.getByRole("button", { name: "Войти", exact: true }).click();
    await platform.getByLabel("Новый пароль").fill("D2 unique platform password 2718!");
    await platform.getByRole("button", { name: "Продолжить" }).click();
    await enrollment(platform);
    await expect(platform).toHaveURL(/\/platform-admin\/$/);
    await expect(platform.getByRole("heading", { name: "Обзор", exact: true })).toBeVisible();
    const platformNav = platform.getByRole("navigation", { name: "Разделы платформы" });
    await platformNav.getByRole("link", { name: "Заявки УК", exact: true }).click();
    await platform.getByRole("button", { name: `ООО ${company}`, exact: true }).click();
    await platform.getByLabel("Основание решения / сообщение для заявителя").fill("Пришлите номер договора управления");
    await platform.getByRole("button", { name: "Запросить уточнения" }).click();
    await expect(platform.getByText("Вопросы и ответы")).toBeVisible();

    await applicant.reload();
    await expect(applicant.getByRole("heading", { name: "Платформе нужны уточнения" })).toBeVisible();
    await expect(applicant.getByText("Пришлите номер договора управления")).toBeVisible();
    await applicant.getByLabel("Ваш ответ").fill("Договор № 7 от 01.09.2026");
    await applicant.getByRole("button", { name: "Отправить ответ" }).click();
    await expect(applicant.getByRole("heading", { name: "Заявка на рассмотрении" })).toBeVisible();

    await platform.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(platform.getByText("Договор № 7 от 01.09.2026")).toBeVisible();
    await platform.getByLabel("Сколько домовых чатов может подключить УК").fill("1");
    await platform.getByLabel("Основание решения / сообщение для заявителя").fill("Начнём с одного чата, расширим по запросу");
    await platform.getByRole("button", { name: "Одобрить УК", exact: true }).click();
    await expect(platform.getByRole("button", { name: "Одобрить УК", exact: true })).toHaveCount(0);
    await expect(platform.getByLabel("Одноразовая ссылка")).toHaveCount(0);

    // 3. Заявитель сам создаёт аккаунт администратора со страницы статуса.
    await applicant.reload();
    await expect(applicant.getByRole("heading", { name: "Заявка одобрена" })).toBeVisible();
    await expect(applicant.getByText("1 чат", { exact: true })).toBeVisible();
    await applicant.getByRole("button", { name: "Создать аккаунт администратора" }).click();
    await expect(applicant.getByRole("heading", { name: "Принять приглашение" })).toBeVisible();
    const inviteUrl = applicant.url();
    const admin = await adminCtx.newPage();
    await admin.goto(inviteUrl);
    await admin.getByLabel("Ваше имя").fill("Администратор D2");
    await admin.getByLabel("Логин", { exact: true }).fill(adminLogin);
    await admin.getByLabel("Пароль", { exact: true }).fill(PASSWORD);
    await admin.getByRole("button", { name: "Создать аккаунт и настроить MFA" }).click();
    await enrollment(admin);
    await expect(admin.getByRole("heading", { name: "Обзор", exact: true })).toBeVisible();
    await expect(admin.getByText("0 из 1")).toBeVisible();
    await applicant.goto(statusUrl);
    await expect(applicant.getByRole("link", { name: "Войти в кабинет" })).toBeVisible();

    // 4. Квота: первый чат подключается, второй — «лимит исчерпан» → расширение.
    d2("house", inn, `Казань, ул. Проверочная, ${suffix}`);
    const nav = admin.getByRole("navigation", { name: "Разделы кабинета" });
    await nav.getByRole("link", { name: "MAX-чаты", exact: true }).click();
    await expect(admin.getByText("0 из 1")).toBeVisible();
    await admin.getByRole("button", { name: "Подключить существующий MAX-чат" }).click();
    await expect(admin.getByText("После подключения останется свободных слотов: 0 из 1.")).toBeVisible();
    const first = (await admin.getByLabel("Команда подключения MAX").inputValue()).replace("/start ", "");
    expect(d2("connect", first, `d2-${suffix}-1`, adminLogin).status).toBe("active");
    await admin.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(admin.getByText("1 из 1")).toBeVisible();
    await admin.getByRole("button", { name: "Подключить существующий MAX-чат" }).click();
    await expect(admin.getByRole("alert")).toContainText("Лимит исчерпан");
    await admin.getByLabel("Сколько чатов добавить").fill("1");
    await admin.getByLabel("Обоснование").fill("Второй чат — подъезд 2");
    await admin.getByRole("button", { name: "Отправить запрос" }).click();
    await expect(admin.getByText("Запрос на расширение +1 на рассмотрении платформы.")).toBeVisible();

    await platformNav.getByRole("link", { name: "Запросы квоты", exact: true }).click();
    await expect(platform.getByRole("heading", { name: `${company}: +1` })).toBeVisible();
    await platform.getByLabel("Причина решения").fill("Одобрено для второго подъезда");
    await platform.getByRole("button", { name: "Одобрить", exact: true }).click();
    await expect(platform.getByText("Запросов, ждущих решения, нет.")).toBeVisible();

    await admin.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(admin.getByText("1 из 2")).toBeVisible();
    await admin.getByRole("button", { name: "Подключить существующий MAX-чат" }).click();
    await expect(admin.getByLabel("Команда подключения MAX")).not.toHaveValue(`/start ${first}`);
    const second = (await admin.getByLabel("Команда подключения MAX").inputValue()).replace("/start ", "");
    expect(d2("connect", second, `d2-${suffix}-2`, adminLogin).status).toBe("active");
    await admin.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(admin.getByText("2 из 2")).toBeVisible();

    // 5. Дашборды: обзор УК с CSV и обзор платформы, на телефоне без прокрутки вбок.
    await nav.getByRole("link", { name: "Обзор", exact: true }).click();
    await expect(admin.getByText("2 из 2")).toBeVisible();
    await expect(admin.getByRole("heading", { name: "Сигналы из чатов по дням" })).toBeVisible();
    const download = admin.waitForEvent("download");
    await admin.getByRole("button", { name: "Выгрузить CSV" }).click();
    expect((await download).suggestedFilename()).toBe("domsignal-obzor-7d.csv");
    await admin.getByRole("button", { name: "30 дней" }).click();
    await expect(admin.getByRole("button", { name: "30 дней" })).toHaveAttribute("aria-pressed", "true");
    await admin.setViewportSize({ width: 390, height: 844 });
    await noOverflow(admin);
    await admin.setViewportSize({ width: 1280, height: 900 });
    await platformNav.getByRole("link", { name: "Обзор", exact: true }).click();
    await expect(platform.getByRole("row", { name: new RegExp(company) })).toContainText("2 из 2");
    await expect(platform.getByRole("heading", { name: "Воронка подключения" })).toBeVisible();
    await platform.setViewportSize({ width: 390, height: 844 });
    await noOverflow(platform);
    await platform.setViewportSize({ width: 1280, height: 900 });

    // 6. Сброс пароля/MFA сотрудника по одноразовой ссылке из кабинета.
    await nav.getByRole("link", { name: "Сотрудники", exact: true }).click();
    await admin.getByRole("button", { name: "Пригласить сотрудника", exact: true }).click();
    const operatorInvite = await admin.getByLabel("Одноразовая ссылка").inputValue();
    const operator = await operatorCtx.newPage();
    const operatorLogin = `d2.operator.${suffix}`;
    await operator.goto(new URL(operatorInvite).pathname);
    await operator.getByLabel("Ваше имя").fill(operatorLogin);
    await operator.getByLabel("Логин", { exact: true }).fill(operatorLogin);
    await operator.getByLabel("Пароль", { exact: true }).fill(PASSWORD);
    await operator.getByRole("button", { name: "Создать аккаунт и настроить MFA" }).click();
    await enrollment(operator);
    await admin.reload();
    await admin.getByRole("button", { name: operatorLogin, exact: true }).click();
    await admin.getByRole("button", { name: "Сбросить пароль/MFA" }).click();
    await admin.getByRole("button", { name: "Подтвердить сброс" }).click();
    const resetLink = await admin.getByLabel("Одноразовая ссылка").inputValue();
    expect(resetLink).toContain("/admin/reset/");
    await operator.reload();
    await expect(operator.getByRole("heading", { name: "Вход сотрудника" })).toBeVisible();
    await operator.goto(new URL(resetLink).pathname);
    await expect(operator.getByRole("heading", { name: "Новый пароль" })).toBeVisible();
    await expect(operator.getByText(`Логин: ${operatorLogin}.`, { exact: false })).toBeVisible();
    await operator.getByLabel("Новый пароль").fill("D2 reset employee password 3141!");
    await operator.getByRole("button", { name: "Сохранить пароль" }).click();
    await enrollment(operator);
    await expect(operator.getByRole("navigation", { name: "Разделы кабинета" })).toBeVisible();

    // 7. Открытая регистрация: суперадмин открывает и закрывает ссылку.
    await platformNav.getByRole("link", { name: "Организации", exact: true }).click();
    await platform.getByRole("button", { name: company, exact: true }).click();
    const registration = platform.getByRole("region", { name: "Открытая регистрация сотрудников" });
    await registration.getByLabel("Причина").fill("Доступ для проверки кабинета");
    await registration.getByRole("button", { name: "Открыть регистрацию" }).click();
    const joinUrl = await platform.getByLabel("Одноразовая ссылка").inputValue();
    expect(joinUrl).toContain("/join/");
    const joiner = await joinCtx.newPage();
    await joiner.goto(new URL(joinUrl).pathname);
    await expect(joiner.getByRole("heading", { name: `Регистрация в «${company}»` })).toBeVisible();
    await joiner.getByLabel("Ваше имя").fill("Проверяющий");
    await joiner.getByLabel("Логин", { exact: true }).fill(`d2.join.${suffix}`);
    await joiner.getByLabel("Новый пароль").fill(PASSWORD);
    await joiner.getByRole("button", { name: "Зарегистрироваться и настроить MFA" }).click();
    await enrollment(joiner);
    const joinNav = joiner.getByRole("navigation", { name: "Разделы кабинета" });
    await expect(joinNav.getByRole("link", { name: "Обзор", exact: true })).toBeVisible();
    await expect(joinNav.getByRole("link", { name: "Сотрудники", exact: true })).toHaveCount(0);
    await registration.getByLabel("Причина").fill("Проверка закончена");
    await registration.getByRole("button", { name: "Закрыть регистрацию" }).click();
    await expect(registration.getByText("закрыта")).toBeVisible();
    await expect(registration.getByText(`d2.join.${suffix}`)).toBeVisible();

    // 8. Единый вход администратора: /login → кабинет УК по роли.
    await admin.getByRole("button", { name: "Выйти", exact: true }).click();
    await admin.goto("/login");
    await admin.getByLabel("Логин").fill(adminLogin);
    await admin.getByLabel("Пароль", { exact: true }).fill(PASSWORD);
    await admin.getByRole("button", { name: "Войти", exact: true }).click();
    await admin.getByLabel("Код из приложения").fill(d2("totp", adminLogin).code);
    await admin.getByRole("button", { name: "Продолжить" }).click();
    await expect(admin).toHaveURL(/\/admin\/$/);
    await expect(admin.getByRole("navigation", { name: "Разделы кабинета" })).toBeVisible();
  } finally {
    for (const ctx of [applicantCtx, platformCtx, adminCtx, operatorCtx, joinCtx]) await ctx.close();
    d2("reset-rate");
  }
});
