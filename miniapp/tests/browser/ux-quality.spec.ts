import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

// UX-1: основные сценарии жителя (Ж1–Ж7) и сотрудника (С1–С4) на 390×844 и
// 1280×800 с проверками доступности на каждом экране: axe WCAG 2.2 AA
// (wcag2a, wcag2aa, wcag21aa, wcag22aa), нет прокрутки вбок (320 и 390),
// цели касания ≥ 24 px везде и ≥ 44 px у основных элементов мини-приложения,
// видимый и не перекрытый фокус, Esc закрывает диалог и возвращает фокус.
// Стенд — как у UX-D3: HTTP + PostgreSQL с фикстурами D2/D3 (miniapp/README.md).
const require = createRequire(import.meta.url);

function run(script: string, args: string[]) {
  const r = spawnSync("uv", ["run", "python", script, ...args], { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout.trim().split("\n").at(-1) ?? "{}");
}
async function auth(request: APIRequestContext, actor: string) {
  const response = await request.post("/api/v1/auth/test-session", { data: { actor } });
  expect(response.status()).toBe(200);
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}
const key = () => `ux-q-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function context(browser: Browser, width: number, height = width < 500 ? 844 : 800) {
  const ctx = await browser.newContext({ viewport: { width, height }, bypassCSP: true, reducedMotion: "reduce" });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", (route) => route.abort());
  return ctx;
}

async function settled(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

/** axe с тегами WCAG 2.2 AA, нет прокрутки вбок, цели касания. */
async function audit(page: Page, name: string, { mini = false } = {}) {
  await settled(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${name}: overflow`).toBe(true);
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () =>
    (
      await (window as unknown as { axe: { run: (...a: unknown[]) => Promise<{ violations: { id: string; nodes: { target: string[] }[] }[] }> } }).axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"] },
      })
    ).violations.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target.join(" ")) })),
  );
  expect(violations, `${name}: axe`).toEqual([]);
  const small = await page.evaluate((isMini) => {
    const box = (node: Element) => {
      // Флажок и переключатель: целью служит вся подпись (2.5.8).
      const label = node.matches("input[type=checkbox], input[type=radio]") ? node.closest("label") : null;
      return (label ?? node).getBoundingClientRect();
    };
    const all = [...document.querySelectorAll("a[href], button, input, select, textarea, summary")].filter((node) => {
      const rect = node.getBoundingClientRect();
      if (!rect.width || !rect.height) return false;
      // Ссылка внутри строки текста — исключение 2.5.8.
      if (node.tagName === "A" && getComputedStyle(node).display === "inline") return false;
      const target = box(node);
      return target.width < 24 || target.height < 24;
    });
    // Основные элементы мини-приложения: кнопки, вкладки, строки списков, «Назад».
    const main = isMini
      ? [...document.querySelectorAll(".ds-btn, .ds-tabs a, a.ds-row, .ds-back, .ds-emergency-link, summary")].filter((node) => {
          const rect = node.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && rect.height < 44;
        })
      : [];
    return [...all, ...main].map((node) => node.outerHTML.slice(0, 100));
  }, mini);
  expect(small, `${name}: targets`).toEqual([]);
}

let ids: { company: string; house: string; other_house: string };
let refs: { incident: string; card: string; draft: string; ticket: string };

test.describe.serial("UX-1 quality", () => {
  test.skip(process.env.D3_BROWSER_FIXTURES !== "1" || process.env.D2_BROWSER_FIXTURES !== "1",
    "Needs isolated HTTP/PostgreSQL D2 and D3 fixtures");

  test.beforeAll(async ({ request }) => {
    test.setTimeout(180000);
    ids = run("tests/browser/d3_fixture.py", ["ids"]);
    run("tests/browser/d3_fixture.py", ["binding"]);
    run("tests/browser/d1_fixture.py", ["guest"]);
    const resident = await auth(request, "a16-resident");
    const created = await request.post("/api/v1/reports", {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { house_id: ids.house, category: "elevator", description: "Лифт во втором подъезде не едет, кнопка вызова не горит" },
    });
    expect(created.status()).toBe(201);
    const submitted = await request.post(`/api/v1/houses/${ids.house}/reports/submit`, {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { description: "На улице у остановки не горят фонари, темно" },
    });
    const card = (await submitted.json()).route_outcome_id;
    const draft = await request.post("/api/v1/appeal-drafts", { headers: resident, data: { house_id: ids.house, route_outcome_id: card } });
    const admin = await auth(request, "a16-admin");
    const tickets = await (await request.get(`/api/v1/tickets?house_id=${ids.house}&limit=1`, { headers: admin })).json();
    refs = { incident: (await created.json()).incident.id, card, draft: (await draft.json()).id, ticket: tickets.items[0].id };
  });

  for (const width of [390, 1280]) {
    test(`Ж1–Ж2 первое открытие и дом — ${width}`, async ({ browser }) => {
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      try {
        // Без дома: как попасть в дом, без тупика.
        await page.goto("/?test_actor=d1-guest");
        await expect(page.getByRole("heading", { level: 1, name: "Как открыть свой дом" })).toBeVisible();
        await expect(page.getByRole("button", { name: "Проверить снова" })).toBeVisible();
        await audit(page, `nohouse-${width}`, { mini: true });
        // Дом выбран: сразу «что с домом», главное действие внизу, «Если авария» наверху.
        // (Без выбора при нескольких домах — список «Выберите дом», D-01.)
        await page.goto(`/?test_actor=a16-resident&house=${ids.house}`);
        await expect(page.getByRole("heading", { level: 1, name: "Проблемы дома" })).toBeVisible();
        await expect(page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Проблемы" })).toHaveAttribute("aria-current", "page");
        await expect(page.getByRole("link", { name: /Если авария/ })).toBeVisible();
        const report = page.getByRole("button", { name: "Сообщить о проблеме" });
        await expect(report).toBeInViewport();
        await audit(page, `board-${width}`, { mini: true });
        // Несколько домов без выбора — список «Выберите дом» (D-01); после выбора —
        // переключатель в шапке, а не отдельный экран.
        await page.goto(`/?test_actor=a16-admin`);
        await expect(page.getByRole("heading", { level: 1, name: "Выберите дом" })).toBeVisible();
        await page.goto(`/?test_actor=a16-admin&house=${ids.house}`);
        const switcher = page.getByRole("button", { name: /^Дом / });
        await expect(switcher).toBeVisible();
        await switcher.click();
        const options = page.getByRole("listbox", { name: "Дом" });
        await expect(options).toBeFocused();
        await expect(options.getByRole("option", { selected: true })).toHaveCount(1);
        await options.locator(`[role=option]:not([aria-selected=true])`).first().click();
        await expect(page).toHaveURL(new RegExp(`house=${ids.other_house}`));
        await expect(page.getByRole("heading", { level: 1, name: "Проблемы дома" })).toBeVisible();
      } finally {
        await ctx.close();
      }
    });

    test(`Ж3 сообщить о проблеме — ${width}`, async ({ browser }) => {
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      const text = `Не горит свет на лестнице третьего этажа ${Date.now()}`;
      try {
        await page.goto(`/?test_actor=a16-resident&house=${ids.house}`);
        await page.getByRole("button", { name: "Сообщить о проблеме" }).click();
        const field = page.getByRole("textbox", { name: "Опишите проблему" });
        await expect(field).toBeFocused();
        await audit(page, `report-${width}`, { mini: true });
        // Слишком коротко — ошибка у поля, ничего не отправлено.
        await field.fill("свет");
        await page.getByRole("button", { name: "Проверить описание" }).click();
        await expect(page.getByText(/от 5 символов/)).toBeVisible();
        await expect(field).toHaveAttribute("aria-invalid", "true");
        await field.fill(text);
        await page.getByRole("button", { name: "Проверить описание" }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Проверьте, что мы поняли" })).toBeVisible();
        await audit(page, `review-${width}`, { mini: true });
        // «Изменить» возвращает к полю с тем же текстом, а после — снова к проверке.
        await page.getByRole("button", { name: /Изменить описание/ }).click();
        await expect(page.getByRole("textbox", { name: "Опишите проблему" })).toHaveValue(text);
        await page.getByRole("button", { name: "Проверить описание" }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Проверьте, что мы поняли" })).toBeVisible();
        // «Назад» и снова в форму — текст на месте (память приложения, не хранилище браузера).
        await page.getByRole("button", { name: /Назад/ }).first().click();
        await page.getByRole("button", { name: "Сообщить о проблеме" }).click();
        await expect(page.getByRole("textbox", { name: "Опишите проблему" })).toHaveValue(text);
        await page.getByRole("button", { name: "Проверить описание" }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Проверьте, что мы поняли" })).toBeVisible();
        for (const name of ["Нет, это другое", "Сообщить в управляющую компанию", "Сообщить в УК", "Всё верно, отправить"]) {
          const button = page.getByRole("button", { name, exact: true });
          if (await button.count()) {
            await button.first().click();
            break;
          }
        }
        await expect(page.getByRole("heading", { level: 1, name: "Сообщение сохранено" })).toBeVisible();
        await expect(page.getByRole("status").filter({ hasText: /Мои обращения/ })).toBeVisible();
        await audit(page, `result-${width}`, { mini: true });
      } finally {
        await ctx.close();
      }
    });

    test(`Ж3 признаки опасности — памятка первой — ${width}`, async ({ browser }) => {
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      try {
        await page.goto(`/?test_actor=a16-resident&house=${ids.house}&report=1`);
        await page.getByRole("textbox", { name: "Опишите проблему" }).fill("В подъезде сильно пахнет газом");
        await page.getByRole("button", { name: "Проверить описание" }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Проверьте, что мы поняли" })).toBeVisible();
        // Сразу после заголовка — блок безопасности со ссылкой tel:.
        const first = page.locator(".report-flow > section").first();
        await expect(first).toHaveClass(/ds-safety/);
        await expect(first.getByRole("link", { name: /Позвонить/ })).toHaveAttribute("href", /^tel:/);
        await audit(page, `danger-${width}`, { mini: true });
      } finally {
        await ctx.close();
      }
    });

    test(`Ж4–Ж6 проблема, обращения и вход по ссылке — ${width}`, async ({ browser }) => {
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      const base = `/?test_actor=a16-resident&house=${ids.house}`;
      try {
        await page.goto(base);
        await page.getByRole("link", { name: /Лифт во втором подъезде не едет/ }).first().click();
        await expect(page.getByRole("heading", { level: 2, name: "Что происходит" })).toBeVisible();
        await expect(page.getByText(/Заявка T-\d+/).first()).toBeVisible();
        await audit(page, `incident-${width}`, { mini: true });
        // «Назад» возвращает к списку, из которого пришли.
        await page.getByRole("button", { name: /Назад/ }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Проблемы дома" })).toBeVisible();
        await page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Мои обращения" }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Мои обращения" })).toBeVisible();
        await audit(page, `mine-${width}`, { mini: true });
        // Вход по ссылке сразу на вложенный экран: «Назад» ведёт к проблемам дома, а не закрывает приложение.
        await page.goto(`${base}&incident=${refs.incident}`);
        await expect(page.getByRole("heading", { level: 2, name: "Что происходит" })).toBeVisible();
        await page.getByRole("button", { name: /Назад/ }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Проблемы дома" })).toBeVisible();
        for (const [view, title] of [["home", "Мой дом"], ["news", "Объявления"], ["works", "Что сделано в доме"], ["reception", "Запись на приём"]]) {
          await page.goto(`${base}&view=${view}`);
          await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
          await audit(page, `${view}-${width}`, { mini: true });
        }
      } finally {
        await ctx.close();
      }
    });

    test(`Ж7 куда обратиться и черновик — ${width}`, async ({ browser }) => {
      const ctx = await context(browser, width);
      await ctx.grantPermissions(["clipboard-read", "clipboard-write"]);
      const page = await ctx.newPage();
      const base = `/?test_actor=a16-resident&house=${ids.house}`;
      try {
        await page.goto(`${base}&card=${refs.card}`);
        await expect(page.getByRole("heading", { level: 1, name: "Куда обратиться" })).toBeVisible();
        await expect(page.getByRole("heading", { name: "Основание" })).toBeVisible();
        await audit(page, `card-${width}`, { mini: true });
        await page.goto(`${base}&draft=${refs.draft}`);
        await expect(page.getByRole("heading", { level: 1, name: "Черновик обращения" })).toBeVisible();
        await expect(page.getByRole("button", { name: "Скопировать текст" })).toBeVisible();
        const order = await page.locator(".draft-actions .ds-btn").evaluateAll((nodes) =>
          nodes.map((node) => (node.textContent ?? "").replace(/\s+/g, " ").trim()),
        );
        expect(order[0]).toBe("Скопировать текст");
        expect(order[1]).toMatch(/^Открыть официальный сервис/);
        expect(order[2]).toBe("Я отправил(а) обращение");
        await page.getByRole("button", { name: "Скопировать текст" }).click();
        await expect(page.getByRole("status").filter({ hasText: /скопир/i })).toBeVisible();
        await audit(page, `draft-${width}`, { mini: true });
        // «Я отправил(а)» — через подтверждение; Esc закрывает и возвращает фокус.
        const mark = page.getByRole("button", { name: "Я отправил(а) обращение" });
        await mark.focus();
        await page.keyboard.press("Enter");
        await expect(page.getByRole("dialog", { name: "Отметить обращение как отправленное?" })).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog")).toHaveCount(0);
        await expect(mark).toBeFocused();
      } finally {
        await ctx.close();
      }
    });
  }

  test("мини-приложение на 320: без прокрутки вбок и с крупными целями", async ({ browser }) => {
    const ctx = await context(browser, 320, 640);
    const page = await ctx.newPage();
    const base = `/?test_actor=a16-resident&house=${ids.house}`;
    try {
      for (const url of [base, `${base}&report=1`, `${base}&incident=${refs.incident}`, `${base}&card=${refs.card}`,
        `${base}&draft=${refs.draft}`, `${base}&view=home`, `${base}&view=mine`, `${base}&view=news`]) {
        await page.goto(url);
        await expect(page.locator("h1").first()).toBeVisible();
        await audit(page, `320 ${url}`, { mini: true });
      }
    } finally {
      await ctx.close();
    }
  });

  test("клавиатура: фокус виден и не прячется под нижней панелью", async ({ browser }) => {
    const ctx = await context(browser, 390);
    const page = await ctx.newPage();
    try {
      await page.goto(`/?test_actor=a16-resident&house=${ids.house}`);
      await settled(page);
      const bar = await page.locator(".ds-bottom-bar").boundingBox();
      expect(bar).toBeTruthy();
      for (let i = 0; i < 25; i += 1) {
        await page.keyboard.press("Tab");
        const state = await page.evaluate(() => {
          const node = document.activeElement as HTMLElement | null;
          if (!node || node === document.body) return null;
          const rect = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          return { top: rect.top, bottom: rect.bottom, outline: style.outlineStyle, inBar: Boolean(node.closest(".ds-bottom-bar")) };
        });
        if (!state) continue;
        expect(state.outline, "focus is visible").not.toBe("none");
        // Элемент в фокусе не перекрыт липкой панелью (2.4.11).
        if (!state.inBar) expect(state.top).toBeLessThan(bar!.y);
      }
    } finally {
      await ctx.close();
    }
  });

  for (const width of [390, 1280]) {
    test(`С1 вход — ${width}`, async ({ browser }) => {
      run("tests/browser/d2_fixture.py", ["reset-rate"]);
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      try {
        await page.goto("/login");
        const login = page.getByLabel("Логин");
        const password = page.getByLabel("Пароль", { exact: true });
        await expect(login).toHaveAttribute("autocomplete", "username");
        await expect(password).toHaveAttribute("autocomplete", "current-password");
        await audit(page, `login-${width}`);
        await login.fill("ux.nobody");
        await password.fill("wrong password value");
        await page.getByRole("button", { name: "Войти", exact: true }).click();
        const error = page.getByText("Логин или пароль не подошли. Проверьте раскладку клавиатуры и Caps Lock.");
        await expect(error).toBeFocused();
        await expect(password).toHaveAttribute("aria-invalid", "true");
        // Введённое не стирается.
        await expect(login).toHaveValue("ux.nobody");
      } finally {
        await ctx.close();
      }
    });

    test(`С2 и С4 очередь и заявка — ${width}`, async ({ browser }) => {
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      const q = `company=${ids.company}&test_actor=a16-admin`;
      try {
        await page.goto(`/admin/tickets?${q}`);
        await expect(page.getByRole("heading", { level: 1, name: "Заявки" })).toBeVisible();
        await page.getByRole("navigation", { name: "Фильтры заявок" }).getByRole("link", { name: "Новые" }).click();
        await expect(page).toHaveURL(/filter=new/);
        await audit(page, `tickets-${width}`);
        await page.getByRole("link", { name: /^Открыть заявку T-/ }).first().click();
        await expect(page.getByRole("heading", { name: "Действия по заявке" })).toBeVisible();
        if (width >= 1200) {
          // Широкий экран: очередь остаётся рядом с заявкой.
          await expect(page.getByRole("region", { name: "Очередь заявок", exact: true })).toBeVisible();
        }
        await audit(page, `ticket-${width}`);
        const assign = page.getByRole("button", { name: /^(Назначить|Изменить) исполнителя$/ });
        if (await assign.count()) {
          await assign.focus();
          await page.keyboard.press("Enter");
          await expect(page.getByRole("dialog")).toBeVisible();
          await page.keyboard.press("Escape");
          await expect(page.getByRole("dialog")).toHaveCount(0);
          await expect(assign).toBeFocused();
        }
        // Возврат к очереди сохраняет фильтр.
        await page.getByRole("link", { name: "Все заявки" }).click();
        await expect(page).toHaveURL(/filter=new/);
      } finally {
        await ctx.close();
      }
    });

    test(`С3 разбор сигнала — ${width}`, async ({ browser }) => {
      run("tests/browser/signal_fixture.py", ["prepare"]);
      const gas = run("tests/browser/signal_fixture.py", ["gas"]).signal_id as string;
      // Два «возможных» сигнала — чтобы после решения было к чему перейти.
      const weak = run("tests/browser/signal_fixture.py", ["playground"]).signal_id as string;
      run("tests/browser/signal_fixture.py", ["light"]);
      const ctx = await context(browser, width);
      const page = await ctx.newPage();
      try {
        await page.goto("/admin/?test_actor=p5-operator&section=signals");
        await expect(page.getByRole("heading", { level: 1, name: "Сигналы" })).toBeVisible();
        // Опасное отличается и текстом, не только цветом.
        await expect(page.getByText(/Критические сигналы: \d+/)).toBeVisible();
        await audit(page, `signals-${width}`);
        await page.goto(`/admin/?test_actor=p5-operator&section=signals&signal=${gas}`);
        const decision = page.getByRole("region", { name: "Действия по сигналу" });
        await expect(decision).toBeVisible();
        if (width >= 1200) {
          // Основное решение видно без прокрутки.
          const box = await decision.boundingBox();
          expect(box!.y).toBeLessThan(800);
        }
        await audit(page, `signal-${width}`);
        // Закрытие — причина из списка и необязательный комментарий.
        await page.goto(`/admin/?test_actor=p5-operator&section=signals&strength=weak&signal=${weak}`);
        await decision.getByRole("button", { name: "Закрыть", exact: true }).click();
        await page.getByRole("combobox", { name: "Причина" }).selectOption("duplicate");
        await page.getByRole("textbox", { name: /Комментарий/ }).fill("Тот же случай уже в работе");
        await page.getByRole("button", { name: "Закрыть сигнал" }).click();
        await expect(page.getByText("Сигнал закрыт. Причина сохранена.")).toBeVisible();
        if (width >= 1200) {
          // Очередь рядом: после решения — следующий сигнал.
          const next = page.getByRole("link", { name: "Открыть следующий сигнал" });
          await expect(next).toBeVisible();
          await next.click();
          await expect(page.getByRole("region", { name: "Действия по сигналу" })).toBeVisible();
          expect(new URL(page.url()).searchParams.get("signal")).not.toBe(weak);
        }
      } finally {
        await ctx.close();
      }
    });
  }
});
