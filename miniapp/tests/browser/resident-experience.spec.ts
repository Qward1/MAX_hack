import { expect, test, type Page } from "@playwright/test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

// Демо-дом из seed_demo: Казань, RU-TA. Жители — demo, demo-neighbour, demo-third.
const SIZES = [
  { width: 390, height: 844, name: "390" },
  { width: 1280, height: 900, name: "1280" },
] as const;

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

test.beforeEach(async ({ page }) => {
  // Детерминированность: ни CDN, ни аккаунт MAX, ни интернет не нужны.
  await page.route("https://st.max.ru/**", (route) => route.abort());
});

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
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

async function open(page: Page, actor: string) {
  await page.goto(`/?test_actor=${actor}`);
  await expect(page.getByRole("button", { name: "Сообщить", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Сообщить", exact: true }).click();
}

async function describeProblem(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Описание" }).fill(text);
  await page.getByRole("button", { name: "Дальше" }).click();
  await expect(page.getByText("Проверьте, что мы поняли")).toBeVisible();
}

/** Отправить новую проблему, какой бы шаг ни предложила карточка. */
async function sendAsNew(page: Page) {
  for (const name of ["Нет, это другое", "Сообщить в УК", "Всё верно, отправить"]) {
    const button = page.getByRole("button", { name, exact: true });
    if (await button.count()) {
      await button.first().click();
      return;
    }
  }
  throw new Error("Шаг отправки не найден");
}

test("UK route: form → review → ticket → route card", async ({ page }) => {
  await page.setViewportSize(SIZES[0]);
  await open(page, "demo");
  await describeProblem(page, "опять лифт во втором подъезде стоит");

  // Показано только то, что пришло с backend.
  await expect(page.getByText("Подъезд").locator("xpath=following-sibling::dd")).toHaveText("2");
  await expect(page.getByText("Наблюдается с")).toHaveCount(0);
  await expect(
    page.getByText("Это зона ответственности вашей управляющей компании"),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-uk-review-390.png", fullPage: true });

  await sendAsNew(page);
  await expect(page.getByRole("heading", { name: "Что дальше" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Открыть проблему" })).toBeVisible();
  await noOverflow(page);
  await axeCheck(page);

  await page.getByRole("button", { name: "Открыть карточку маршрута" }).click();
  await expect(page).toHaveURL(/card=/);
  await expect(page.getByRole("heading", { name: "Следующий шаг" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Основание" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Открыть проблему дома" })).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-uk-card-390.png", fullPage: true });
  await noOverflow(page);
  await axeCheck(page);

  await page.setViewportSize(SIZES[1]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Основание" })).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-uk-card-1280.png", fullPage: true });
  await noOverflow(page);
});

test("external route: form → review → card → draft → copy → I sent it", async ({ page }) => {
  await page.setViewportSize(SIZES[0]);
  await open(page, "demo");
  await describeProblem(page, "на улице у остановки не горят фонари");
  await expect(page.getByText("Проблема, вероятно, относится не к вашей УК")).toBeVisible();

  await sendAsNew(page);
  await expect(page.getByRole("heading", { name: "Что дальше" })).toBeVisible();
  // Демо-дом в Казани (D4): первый канал — «Народный контроль» (Портал услуг
  // РТ), переход — настоящая ссылка; по ней не переходим, проверяем только адрес.
  const transition = page.getByRole("link", { name: /^Перейти: ГИС РТ «Народный контроль»/ });
  await expect(transition).toHaveAttribute("href", "https://uslugi.tatarstan.ru/open-gov");
  await expect(transition).toHaveAttribute("target", "_blank");
  await expect(page.getByRole("button", { name: /^Перейти: / })).toHaveCount(0);
  await page.screenshot({ path: "test-results/p3c-external-card-390.png", fullPage: true });
  await noOverflow(page);
  await axeCheck(page);

  await page.getByRole("button", { name: "Подготовить текст обращения" }).click();
  await expect(page).toHaveURL(/draft=/);
  await expect(page.getByRole("heading", { name: "Текст обращения" })).toBeVisible();
  const draft = page.getByRole("textbox", { name: "Обращение" });
  await expect(draft).toContainText("Суть проблемы или предложения:");
  await expect(draft).toContainText("на улице у остановки не горят фонари");
  // P7b: факты канала с источниками — на экране рядом, в текст обращения не входят.
  await expect(draft).not.toContainText("Источник");
  await expect(page.getByRole("heading", { name: "Что известно о канале" })).toBeVisible();
  await expect(
    page.getByText("ДомСигнал не отправляет обращения за вас — вы отправляете его сами."),
  ).toBeVisible();

  // Порядок действий на экране черновика закреплён продуктом.
  const labels = await page
    .locator(".draft-actions button, .draft-actions a")
    .evaluateAll((nodes) => nodes.map((node) => node.textContent?.trim()));
  expect(labels).toEqual([
    "Скопировать текст",
    "Открыть официальный сервис ↗",
    "Я отправил(а) обращение",
  ]);
  await expect(
    page.getByRole("link", { name: "Открыть официальный сервис" }),
  ).toHaveAttribute("href", "https://uslugi.tatarstan.ru/open-gov");
  await expect(page.getByText(/^Вход: /)).toHaveCount(0);

  await page.screenshot({ path: "test-results/p3c-draft-390.png", fullPage: true });
  await noOverflow(page);
  // Проверка идёт в состоянии покоя: рябь нажатия — переходная анимация MaxUI.
  await axeCheck(page);

  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  await page.getByRole("button", { name: "Скопировать текст" }).click();
  await expect(
    page.getByText(/Текст скопирован\.|Выделите и скопируйте текст вручную\./),
  ).toBeVisible();
  expect(problems).toEqual([]);

  await page.getByLabel(/Номер обращения/).fill("OBR-DEMO-1");
  await page.getByRole("button", { name: "Я отправил(а) обращение" }).click();
  await expect(
    page.getByText(
      "Вы отметили, что отправили обращение. ДомСигнал не подтверждает регистрацию во внешней системе.",
      { exact: false },
    ),
  ).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Обращение" })).toBeDisabled();
  await page.screenshot({ path: "test-results/p3c-draft-filed-390.png", fullPage: true });

  await page.setViewportSize(SIZES[1]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Текст обращения" })).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-draft-1280.png", fullPage: true });
  await noOverflow(page);

  // Возврат ведёт на карточку того же исхода.
  await page.getByRole("button", { name: /К карточке маршрута/ }).click();
  await expect(page).toHaveURL(/card=/);
  await expect(page.getByRole("heading", { name: "Следующий шаг" })).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-external-card-1280.png", fullPage: true });
});

test("duplicate: the second resident joins, the third creates a new problem", async ({ page }) => {
  await page.setViewportSize(SIZES[1]);
  const text = "в подъезде переполнен мусоропровод";

  await open(page, "demo");
  await describeProblem(page, text);
  await sendAsNew(page);
  await expect(page.getByRole("heading", { name: "Что дальше" })).toBeVisible();

  await open(page, "demo-neighbour");
  await describeProblem(page, text);
  await expect(page.getByText("Похоже, об этом уже сообщали")).toBeVisible();
  await expect(page.getByRole("button", { name: "Это та же проблема" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Нет, это другое" })).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-duplicates-1280.png", fullPage: true });
  await noOverflow(page);
  await axeCheck(page);

  await page.getByRole("button", { name: "Это та же проблема" }).first().click();
  await expect(
    page.getByRole("heading", { name: "Вы присоединились к существующей проблеме" }),
  ).toBeVisible();
  await expect(page.getByText(/участников: [2-9]/)).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-joined-1280.png", fullPage: true });

  await open(page, "demo-third");
  await describeProblem(page, text);
  await expect(page.getByText("Похоже, об этом уже сообщали")).toBeVisible();
  await page.getByRole("button", { name: "Нет, это другое" }).click();
  await expect(page.getByRole("heading", { name: "Что дальше" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Открыть проблему" })).toBeVisible();
  await page.getByRole("button", { name: "Открыть проблему" }).click();
  await expect(page).toHaveURL(/incident=/);
  await expect(page.getByRole("heading", { name: "Что делать сейчас" })).toBeVisible();
  await page.screenshot({ path: "test-results/p3c-new-problem-1280.png", fullPage: true });
});

test("a route-card launch link opens the card for its recipient only", async ({
  page,
  request,
}) => {
  const session = await request.post("/api/v1/auth/test-session", { data: { actor: "demo" } });
  const token = (await session.json()).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const me = await (await request.get("/api/v1/me", { headers })).json();
  const house = me.houses[0].id;
  const submitted = await request.post(`/api/v1/houses/${house}/reports/submit`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { description: "на улице у остановки не горят фонари" },
  });
  expect(submitted.status()).toBe(201);
  const outcome = (await submitted.json()).route_outcome_id;

  await page.goto(`/?test_actor=demo&card=${outcome}`);
  await expect(page.getByRole("heading", { name: "Следующий шаг" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Что известно о канале" })).toBeVisible();

  // Чужому исход неотличим от несуществующего.
  await page.goto(`/?test_actor=demo-third&card=${outcome}`);
  await expect(page.getByText("Проблема не найдена", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Что известно о канале" })).toHaveCount(0);
});
