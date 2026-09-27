import { test, expect, type Page } from "@playwright/test";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const houseId = "00000000-0000-0000-0000-000000000101";
const incidentId = "00000000-0000-0000-0000-000000000201";
const longAddress =
  "УлицаОченьДлинногоНазвания".repeat(8) + ", дом 123, корпус 45";
const longText =
  "ОписаниеБезПробелов".repeat(70) + "\nВесь значимый текст должен быть виден.";
const longSource = "ОрганизацияСОченьДлиннымНазванием".repeat(8);
const fixture = {
  id: incidentId,
  house_id: houseId,
  title: "Не работает лифт",
  description: longText,
  category: "future-category",
  status: "future-status",
  report_count: 9999,
  created_at: "2026-09-17T12:00:00Z",
  allowed_actions: [{ code: "future-action", enabled: true, reason: null }],
  participant_count: 1,
  provenance: null,
  updated_at: null,
  due_at: null,
  location: null,
  is_demo: true,
  rule: {
    origin: null,
    verification_status: "future-source",
    source_title: longSource,
    source_url: "https://example.org/rules",
    due_at: null,
    note: "Источник ещё не проверен",
  },
  reports: [],
};

test.beforeEach(async ({ page }) => {
  // Test determinism: no external CDN, MAX account or internet is required.
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
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
      })
    ).violations.map((v: any) => ({
      id: v.id,
      targets: v.nodes.map((n: any) => n.target),
    })),
  );
  expect(violations).toEqual([]);
}
async function tortureRoutes(page: Page) {
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      json: {
        id: "user",
        display_name: "Житель",
        houses: [
          {
            id: houseId,
            name: "Демонстрационный дом",
            address: longAddress,
            role: "resident",
            is_demo: true,
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/houses/*/incidents?*", (route) =>
    route.fulfill({
      json: {
        items: Array.from({ length: 100 }, (_, i) => ({
          ...fixture,
          id: i === 0 ? incidentId : String(i),
          title: i === 0 ? fixture.title : `Сигнал ${i}`,
          report_count: [0, 1, 9999][i % 3],
        })),
        page: { limit: 100, offset: 0, total: 100 },
      },
    }),
  );
  await page.route("**/api/v1/incidents/*", (route) =>
    route.fulfill({ json: fixture }),
  );
}

test("real API → PostgreSQL → board → detail → reload; web keyboard and retry", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Сообщить о проблеме", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Сообщить о проблеме", exact: true }).click();
  const description = `B-02 browser acceptance ${Date.now()}: лифт не работает`;
  await page.getByRole("textbox", { name: "Опишите проблему" }).fill(description);
  await page.getByRole("button", { name: "Проверить описание" }).click();
  await expect(page.getByText("Проверьте, что мы поняли")).toBeVisible();
  const created = page.waitForResponse(
    (response) =>
      response.url().includes("/reports/submit") &&
      response.request().method() === "POST",
  );
  // Дубль того же лифта мог остаться от предыдущего прогона: житель решает сам.
  for (const name of ["Нет, это другое", "Сообщить в управляющую компанию", "Сообщить в УК", "Всё верно, отправить"]) {
    const button = page.getByRole("button", { name, exact: true });
    if (await button.count()) {
      await button.first().click();
      break;
    }
  }
  const response = await created;
  expect(response.status()).toBe(201);
  const id = (await response.json()).report.incident.id;
  await expect(page.getByRole("heading", { name: "Сообщение сохранено" })).toBeVisible();
  await page.getByRole("button", { name: "Открыть проблему" }).click();
  await expect(page).toHaveURL(new RegExp(`incident=${id}`));
  await page.goBack();
  const link = page.locator(`a[href*="incident=${id}"]`);
  await page.screenshot({
    path: "test-results/real-board.png",
    fullPage: true,
  });
  await link.first().focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Что известно" }),
  ).toBeVisible();
  await expect(
    page
      .locator("section")
      .filter({
        has: page.getByRole("heading", { name: "Что известно", exact: true }),
      }),
  ).toContainText(description);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Что известно" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/real-detail.png",
    fullPage: true,
  });
  await expect(page.locator(".ds-source summary").last()).toContainText(
    "Пример данных ДомСигнала",
  );
  await expect(
    page.getByRole("button", { name: "Подготовить обращение" }),
  ).toHaveCount(0);
  const summary = page.locator(".ds-source summary").last();
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".ds-source").last()).toHaveAttribute("open", "");
  await page.keyboard.press("Space");
  await expect(page.locator(".ds-source").last()).not.toHaveAttribute("open", "");
  // «Назад» возвращает туда, откуда пришли (история), а не открывает доску заново.
  await page.getByRole("button", { name: /Назад/ }).focus();
  await page.keyboard.press("Space");
  await expect(
    page.getByRole("heading", { name: /Проблемы дома/ }),
  ).toBeVisible();
  await page.goForward();
  await expect(
    page.getByRole("heading", { name: "Что известно" }),
  ).toBeVisible();
  await page.route(`**/api/v1/incidents/${id}*`, (route) => route.abort(), {
    times: 1,
  });
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByText(/Показаны данные, загруженные раньше/)).toBeVisible();
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.getByText(/Показаны данные, загруженные раньше/)).toHaveCount(0);
  await noOverflow(page);
  await axeCheck(page);
  expect(
    await page.evaluate(
      () => window.localStorage.length + window.sessionStorage.length,
    ),
  ).toBe(0);
  // The actual C0 backend rejects a foreign actor; frontend may not reveal the cached card.
  const session = await request.post("/api/v1/auth/test-session", {
    data: { actor: "outsider" },
  });
  const token = (await session.json()).access_token;
  await page.route(`**/api/v1/incidents/${id}*`, (route) =>
    route.continue({
      headers: {
        ...route.request().headers(),
        authorization: `Bearer ${token}`,
      },
    }),
  );
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByText("Проблема не найдена")).toBeVisible();
  await expect(page.getByText(description, { exact: true })).toHaveCount(0);
});

for (const width of [320, 430, 1280])
  for (const theme of ["light", "dark"] as const) {
    test(`torture: ${width}px ${theme}, 100 incidents, unknown/null, full text and focus`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme: theme });
      await tortureRoutes(page);
      await page.goto("/");
      await expect(
        page.getByRole("list", { name: "Проблемы дома" }).getByRole("link"),
      ).toHaveCount(100);
      await noOverflow(page);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Проблемы дома");
      await expect(page.getByText(longAddress, { exact: true })).toBeVisible();
      await page.screenshot({
        path: `test-results/board-${width}-${theme}.png`,
      });
      const link = page.locator(`a[href*="incident=${incidentId}"]`);
      await link.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expect(link).toBeFocused();
      expect(
        await link.evaluate(
          (element) => getComputedStyle(element).outlineStyle,
        ),
      ).not.toBe("none");
      await page.keyboard.press("Enter");
      await expect(
        page.getByRole("heading", { name: "Что известно" }),
      ).toBeVisible();
      await expect(page.getByText(longText, { exact: true })).toBeVisible();
      // Срок неизвестен — строки «Срок» нет, он не выдумывается.
      await expect(page.getByText("Срок", { exact: true })).toHaveCount(0);
      await expect(page.locator(".ds-tag").first()).toContainText(
        "Состояние обновилось",
      );
      await expect(
        page.getByRole("button", { name: /future-action/ }),
      ).toHaveCount(0);
      await page.locator(".ds-source summary").last().focus();
      await page.keyboard.press("Enter");
      await expect(page.getByText(longSource, { exact: true })).toBeVisible();
      await noOverflow(page);
      await axeCheck(page);
      await page.screenshot({
        path: `test-results/detail-${width}-${theme}.png`,
        fullPage: true,
      });
      await expect(page.locator(".diagnostics")).toHaveCount(0);
    });
  }

test("missing source, empty list, loading, initial errors and retry", async ({
  page,
}) => {
  await tortureRoutes(page);
  let ready!: () => void;
  const release = new Promise<void>((resolve) => {
    ready = resolve;
  });
  await page.route("**/api/v1/houses/*/incidents?*", async (route) => {
    await release;
    await route.fulfill({
      json: { items: [], page: { limit: 100, offset: 0, total: 0 } },
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Загружаем проблемы дома" }),
  ).toBeVisible();
  ready();
  await expect(page.getByText("О проблемах пока не сообщали")).toBeVisible();
  await page.route("**/api/v1/incidents/*", (route) =>
    route.fulfill({
      json: { ...fixture, rule: null, reports: [], allowed_actions: [] },
    }),
  );
  await page.goto(`/?incident=${incidentId}`);
  await expect(page.getByText("Что известно")).toBeVisible();
  await expect(page.locator(".ds-source")).toHaveCount(0);
  for (const [status, title] of [
    [401, "Сессия MAX истекла"],
    [403, "Нет доступа к этому дому"],
    [404, "Проблема не найдена"],
    [409, "Данные изменились"],
    [503, "Не удалось загрузить проблему"],
  ] as const) {
    await page.route(
      "**/api/v1/incidents/*",
      (route) =>
        route.fulfill({
          status,
          contentType: "application/problem+json",
          json: { status, detail: "private unsafe details" },
        }),
      { times: 1 },
    );
    await page.goto(`/?incident=${incidentId}`);
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expect(page.getByText("private unsafe details")).toHaveCount(0);
    if (status >= 500 || status === 409) {
      await page.getByRole("button", { name: "Повторить" }).click();
      await expect(page.getByText("Что известно")).toBeVisible();
    }
  }
});
