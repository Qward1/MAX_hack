import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

// F1 §2.5 — автоматическая проверка вёрстки. Все экраны всех поверхностей
// (мини-приложение, кабинеты УК и платформы, вход, заявка УК, лендинг) на
// ширинах 320, 390, 768, 1280, 1440 в светлой и тёмной теме. На каждом:
// нет прокрутки вбок; рамки интерактивных элементов и текстовые блоки не
// накладываются; между интерактивными ≥ 8 px, от текста до кнопки под ним
// ≥ 12 px; цели нажатия ≥ 44 px при ширине ≤ 430; нет синего подчёркнутого
// текста (кроме `ds-text-link`); у кнопки есть рамка, фон или значок; на
// экране нет UUID, undefined, null, NaN и «..»; текст не обрезан без
// многоточия; axe WCAG 2.2 AA — 0 нарушений.
// Стенд — как у UX-D3: HTTP + PostgreSQL с фикстурами D2/D3 (miniapp/README.md).
const require = createRequire(import.meta.url);
const WIDTHS = (process.env.UI_LINT_WIDTHS ?? "320,390,768,1280,1440").split(",").map(Number);
const THEMES = (process.env.UI_LINT_THEMES ?? "light,dark").split(",") as ("light" | "dark")[];
const HEIGHT: Record<number, number> = { 320: 640, 390: 844, 768: 1024, 1280: 800, 1440: 900 };
const STATE = "test-results/ui-lint/platform-state.json";

function run(script: string, args: string[]) {
  const r = spawnSync("uv", ["run", "python", script, ...args], { cwd: "..", encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout.trim().split("\n").at(-1) ?? "{}");
}
const d3 = (...args: string[]) => run("tests/browser/d3_fixture.py", args);
const d2 = (...args: string[]) => run("tests/browser/d2_fixture.py", args);
const enrollOtp = () => run("tests/browser/employee_fixture.py", ["otp"]).code as string;
const key = () => `ui-lint-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function auth(request: APIRequestContext, actor: string) {
  const response = await request.post("/api/v1/auth/test-session", { data: { actor } });
  expect(response.status()).toBe(200);
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}

/** Проверки одного экрана в браузере: список замечаний словами. */
async function lint(page: Page, narrow: boolean): Promise<string[]> {
  return page.evaluate((narrow) => {
    const out: string[] = [];
    const describe = (el: Element) => {
      const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 36);
      const cls = typeof el.className === "string" && el.className.trim()
        ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      return `${el.tagName.toLowerCase()}${cls}${text ? ` «${text}»` : ""}`;
    };
    const hidden = (el: Element) => {
      if (el.closest(".ds-visually-hidden, .sr-only, .visually-hidden, [hidden], dialog:not([open]), [aria-hidden=true]")) return true;
      // Содержимое закрытого раскрытия не показано, хотя у элементов есть рамки.
      for (let d = el.closest("details:not([open])"); d; d = d.parentElement?.closest("details:not([open])") ?? null) {
        if (!d.querySelector(":scope > summary")?.contains(el)) return true;
      }
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return true;
      // «Перейти к содержанию» и подобные — за краем, пока нет фокуса.
      if (r.right + scrollX < 0 || r.bottom + scrollY < 0) return true;
      for (let n: Element | null = el; n; n = n.parentElement) {
        const s = getComputedStyle(n);
        if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) return true;
        if (s.clipPath === "inset(50%)" || s.clip === "rect(0px, 0px, 0px, 0px)") return true;
      }
      return false;
    };
    const floating = (el: Element) => {
      for (let n: Element | null = el; n; n = n.parentElement) {
        const p = getComputedStyle(n).position;
        if (p === "fixed" || p === "sticky") return true;
      }
      return false;
    };
    const box = (el: Element) => {
      const r = el.getBoundingClientRect();
      return { l: r.left + scrollX, t: r.top + scrollY, r: r.right + scrollX, b: r.bottom + scrollY, h: r.height, w: r.width };
    };
    type Box = ReturnType<typeof box>;
    const overlapX = (a: Box, b: Box) => Math.min(a.r, b.r) - Math.max(a.l, b.l);
    const overlapY = (a: Box, b: Box) => Math.min(a.b, b.b) - Math.max(a.t, b.t);
    const nested = (a: Element, b: Element) => a.contains(b) || b.contains(a);
    const rgba = (value: string) => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return [0, 0, 0, 0];
      const parts = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return [parts[0], parts[1], parts[2], parts[3] ?? 1];
    };

    // 1. Прокрутка вбок.
    if (document.documentElement.scrollWidth > innerWidth + 1) {
      out.push(`прокрутка вбок: ширина ${document.documentElement.scrollWidth} при окне ${innerWidth}`);
    }

    const INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=tab], [role=button]";
    const interactive = [...document.querySelectorAll(INTERACTIVE)].filter((el) => !hidden(el));
    const inFlow = interactive.filter((el) => !floating(el));
    const TEXT = "p, h1, h2, h3, h4, legend, dt, dd";
    const texts = [...document.querySelectorAll(TEXT)].filter((el) => !hidden(el) && !floating(el) && (el.textContent ?? "").trim());

    // 2. Наложение рамок: интерактивные между собой, с текстом и текст с текстом.
    const blocks = [...inFlow, ...texts];
    const boxes = blocks.map(box);
    for (let i = 0; i < blocks.length; i++) {
      for (let j = i + 1; j < blocks.length; j++) {
        const a = blocks[i], b = blocks[j];
        if (nested(a, b) || a.closest("label") === b.closest("label") && a.closest("label")) continue;
        if (overlapX(boxes[i], boxes[j]) > 2 && overlapY(boxes[i], boxes[j]) > 2) {
          out.push(`наложение: ${describe(a)} × ${describe(b)}`);
        }
      }
    }

    // 3. Промежутки между интерактивными ≥ 8 px. Сплошные наборы — вкладки,
    // меню, строки списков, раскрытия и таблицы — разделены рамкой, а не зазором.
    const joined = (el: Element) => el.matches("summary, .ds-row, a.ds-row, .staff-row, [role=tab], input[type=checkbox], input[type=radio]")
      || !!el.closest("nav, [role=tablist], table, .ds-tabs, .ds-list, .admin-nav, fieldset.choice-row, .ds-segmented");
    const ib = inFlow.map(box);
    for (let i = 0; i < inFlow.length; i++) {
      for (let j = i + 1; j < inFlow.length; j++) {
        const a = inFlow[i], b = inFlow[j];
        if (nested(a, b) || joined(a) || joined(b)) continue;
        let gap: number | null = null;
        if (overlapY(ib[i], ib[j]) > 4) gap = -overlapX(ib[i], ib[j]);
        else if (overlapX(ib[i], ib[j]) > 4) gap = -overlapY(ib[i], ib[j]);
        if (gap !== null && gap >= 0 && gap < 7.5) out.push(`зазор ${Math.round(gap)} px: ${describe(a)} и ${describe(b)}`);
      }
    }
    // От текста до кнопки под ним ≥ 12 px.
    for (const el of inFlow.filter((n) => n.matches(".ds-btn, .ticket-button, .admin-button"))) {
      const unit = el.closest(".button-row, .page-actions, .ds-actions") ?? el;
      const prev = unit.previousElementSibling;
      if (!prev || !prev.matches("p, h1, h2, h3, h4, ul, ol, dl, .muted") || hidden(prev)) continue;
      const a = box(prev), b = box(el);
      const gap = b.t - a.b;
      if (overlapX(a, b) > 4 && gap >= 0 && gap < 12) out.push(`текст вплотную к кнопке (${Math.round(gap)} px): ${describe(prev)} → ${describe(el)}`);
    }

    // 4. Цели нажатия ≥ 44 px на телефоне. Ссылка внутри строки текста — исключение.
    if (narrow) {
      for (const el of interactive) {
        if (el.matches("input[type=checkbox], input[type=radio]")) continue;
        if (el.tagName === "A" && getComputedStyle(el).display === "inline") continue;
        const r = el.getBoundingClientRect();
        if (r.height < 43.5) out.push(`цель ${Math.round(r.width)}×${Math.round(r.height)} px: ${describe(el)}`);
      }
    }

    const withText = [...document.body.querySelectorAll("*")].filter((el) =>
      [...el.childNodes].some((n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? "").trim()) && !hidden(el));

    // 5. Синий подчёркнутый текст — только `ds-text-link`.
    for (const el of withText) {
      const s = getComputedStyle(el);
      if (!s.textDecorationLine.includes("underline") || el.closest(".ds-text-link")) continue;
      const [r, g, b] = rgba(s.color);
      if (b >= 140 && b - r >= 60 && b - g >= 40) out.push(`синий подчёркнутый текст: ${describe(el)}`);
    }

    // 6. У кнопки есть рамка, фон или значок.
    for (const el of interactive.filter((n) => n.matches("button, a.ds-btn, [role=button]") && !n.matches("[role=tab]") && !n.closest("nav, [role=tablist]"))) {
      const s = getComputedStyle(el);
      const bg = rgba(s.backgroundColor)[3] > 0 || s.backgroundImage !== "none";
      const border = ["Top", "Right", "Bottom", "Left"].some((side) =>
        parseFloat(s.getPropertyValue(`border-${side.toLowerCase()}-width`)) > 0 && rgba(s.getPropertyValue(`border-${side.toLowerCase()}-color`))[3] > 0);
      // Значок — SVG, картинка, псевдоэлемент (символ или нарисованный рамкой
      // шеврон) или символ-стрелка в начале или конце подписи: ← ↻ › ↗.
      const pseudo = ["::before", "::after"].some((part) => {
        const ps = getComputedStyle(el, part);
        if (!ps.content || ps.content === "none" || ps.content === "normal") return false;
        return ps.content !== '""' || parseFloat(ps.borderRightWidth) > 0 || parseFloat(ps.borderBottomWidth) > 0
          || rgba(ps.backgroundColor)[3] > 0 || ps.backgroundImage !== "none" || ps.maskImage !== "none";
      });
      const label = (el.textContent ?? "").trim();
      const glyph = /^[←→↻↗›‹✓✕×+↓↑]/.test(label) || /[←→↻↗›‹✓✕↓↑]$/.test(label);
      const icon = glyph || !!el.querySelector("svg, img, .ds-icon, [class*=icon]");
      if (!bg && !border && !pseudo && !icon) out.push(`кнопка без рамки, фона и значка: ${describe(el)}`);
    }

    // 7. Служебные значения на экране.
    const visibleText = document.body.innerText;
    const bad: [RegExp, string][] = [
      [/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i, "UUID"],
      [/\bundefined\b/, "undefined"], [/\bnull\b/, "null"], [/\bNaN\b/, "NaN"],
      [/(?<![.…])\.\.(?![.\/])/, "«..»"],
    ];
    for (const [re, name] of bad) {
      const m = visibleText.match(re);
      if (m) out.push(`${name} на экране: …${visibleText.slice(Math.max(0, (m.index ?? 0) - 30), (m.index ?? 0) + 30).replace(/\s+/g, " ")}…`);
    }

    // 8. Обрезанный текст без многоточия.
    for (const el of withText) {
      if (el.matches("input, select, textarea, option, code, pre")) continue;
      const s = getComputedStyle(el);
      const clipsX = ["hidden", "clip"].includes(s.overflowX);
      if (clipsX && el.scrollWidth > el.clientWidth + 1 && s.textOverflow !== "ellipsis") {
        out.push(`текст обрезан без многоточия: ${describe(el)}`);
      }
    }
    return [...new Set(out)];
  }, narrow);
}

async function axe(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  return page.evaluate(async () =>
    ((await (window as any).axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"] } })).violations
      .map((v: any) => `axe ${v.id}: ${v.nodes.slice(0, 3).map((n: any) => n.target.join(" ")).join(", ")}`)));
}

async function settled(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 15000 });
  await page.waitForTimeout(150);
}

type Scene = { name: string; platform?: boolean; open: (page: Page) => Promise<void> };
let ids: { company: string; house: string };
let refs: { incident: string; card: string; draft: string; ticket: string; status: string };

async function h1(page: Page) {
  await page.getByRole("heading", { level: 1 }).first().waitFor();
}
async function review(page: Page, text: string) {
  await page.goto(`/?test_actor=a16-resident&house=${ids.house}&report=1`);
  await page.locator("textarea").first().fill(text);
  await page.locator("form button[type=submit]").first().click();
  await page.waitForFunction(() => !document.querySelector("form textarea"), null, { timeout: 15000 });
}
const resident = (query: string, name: string): Scene => ({
  name, open: async (page) => { await page.goto(`/?test_actor=a16-resident&house=${ids.house}${query}`); await h1(page); },
});
const cabinet = (path: string, name: string, actor = "a16-admin"): Scene => ({
  name, open: async (page) => { await page.goto(`/admin/${path}${path.includes("?") ? "&" : "?"}test_actor=${actor}`); await h1(page); },
});
const platform = (path: string): Scene => ({
  name: `platform-${path || "overview"}`, platform: true,
  open: async (page) => { await page.goto(`/platform-admin/${path}`); await h1(page); },
});
const scenes = (): Scene[] => [
  { name: "resident-no-house", open: async (page) => { await page.goto("/?test_actor=d1-guest"); await h1(page); } },
  resident("", "resident-board"),
  resident("&report=1", "resident-report"),
  { name: "resident-review", open: (page) => review(page, "С утра нет горячей воды в квартирах второго подъезда, пятый этаж") },
  { name: "resident-review-danger", open: (page) => review(page, "На лестнице третьего подъезда сильно пахнет газом") },
  resident(`&incident=${refs.incident}`, "resident-incident"),
  resident(`&card=${refs.card}`, "resident-card"),
  resident(`&draft=${refs.draft}`, "resident-draft"),
  resident("&view=home", "resident-home"),
  resident("&view=mine", "resident-mine"),
  resident("&view=news", "resident-news"),
  cabinet("", "cabinet-overview"),
  cabinet("tickets", "cabinet-tickets"),
  cabinet(`?ticket=${refs.ticket}`, "cabinet-ticket"),
  cabinet("?section=signals", "cabinet-signals"),
  cabinet("houses", "cabinet-houses"),
  cabinet("staff", "cabinet-staff"),
  cabinet("max", "cabinet-max"),
  cabinet("organization", "cabinet-organization"),
  cabinet("mailings", "cabinet-mailings"),
  cabinet("notices", "cabinet-notices"),
  cabinet("reception", "cabinet-reception"),
  cabinet("houses", "operator-houses", "a16-responsible"),
  cabinet("tickets", "operator-tickets", "a16-operator"),
  platform(""),
  platform("applications"),
  platform("quota-requests"),
  platform("companies"),
  platform("house-management-requests"),
  platform("houses"),
  platform("binding-disputes"),
  platform("health"),
  platform("audit"),
  platform("mailings"),
  { name: "site-landing", open: async (page) => { await page.goto("/site"); await h1(page); } },
  { name: "site-login", open: async (page) => { await page.goto("/login"); await h1(page); } },
  { name: "site-apply", open: async (page) => { await page.goto("/company/apply"); await h1(page); } },
  { name: "site-apply-status", open: async (page) => { await page.goto(refs.status); await h1(page); } },
  { name: "site-privacy", open: async (page) => { await page.goto("/privacy"); await h1(page); } },
];

async function context(browser: Browser, width: number, theme: "light" | "dark", signedIn: boolean): Promise<BrowserContext> {
  const ctx = await browser.newContext({
    viewport: { width, height: HEIGHT[width] ?? 900 }, colorScheme: theme, reducedMotion: "reduce", bypassCSP: true,
    storageState: signedIn ? STATE : undefined,
  });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", (route) => route.abort());
  return ctx;
}

test.describe.serial("F1 ui-lint", () => {
  test.skip(process.env.D3_BROWSER_FIXTURES !== "1" || process.env.D2_BROWSER_FIXTURES !== "1",
    "Needs isolated HTTP/PostgreSQL D2 and D3 fixtures");

  test.beforeAll(async ({ browser, request }) => {
    test.setTimeout(240000);
    mkdirSync("test-results/ui-lint", { recursive: true });
    ids = d3("ids");
    d3("binding");
    run("tests/browser/d1_fixture.py", ["guest"]);
    const residentAuth = await auth(request, "a16-resident");
    const created = await request.post("/api/v1/reports", {
      headers: { ...residentAuth, "Idempotency-Key": key() },
      data: { house_id: ids.house, category: "elevator", description: "Лифт во втором подъезде не едет, кнопка вызова не горит" },
    });
    expect(created.status()).toBe(201);
    const submitted = await request.post(`/api/v1/houses/${ids.house}/reports/submit`, {
      headers: { ...residentAuth, "Idempotency-Key": key() },
      data: { description: "На улице у остановки не горят фонари, темно" },
    });
    const card = (await submitted.json()).route_outcome_id;
    const draft = await request.post("/api/v1/appeal-drafts", { headers: residentAuth, data: { house_id: ids.house, route_outcome_id: card } });
    const admin = await auth(request, "a16-admin");
    const tickets = await (await request.get(`/api/v1/tickets?house_id=${ids.house}&limit=1`, { headers: admin })).json();
    const inn = String(7700000000 + Math.floor(Math.random() * 99999999)).slice(0, 10);
    const application = await request.post("/api/v1/onboarding/company-applications", {
      data: { legal_name: "ООО «Проверка вёрстки»", short_name: "Проверка вёрстки", inn, contact_name: "Мария Иванова",
        contact_email: "uk@example.org", requested_chat_count: 2, house_addresses: ["Казань, ул. Проверочная, 3"] },
    });
    expect(application.status()).toBe(202);
    refs = {
      incident: (await created.json()).incident.id, card, draft: (await draft.json()).id, ticket: tickets.items[0].id,
      status: new URL((await application.json()).status_url).pathname,
    };

    // Вход платформы: пароль → новый пароль → код из приложения → коды восстановления.
    d2("reset-rate");
    const setup = d2("platform");
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto("/login");
    await page.getByLabel("Логин").fill("d2.platform");
    await page.getByLabel("Пароль", { exact: true }).fill(setup.password);
    await page.getByRole("button", { name: "Войти", exact: true }).click();
    await page.getByLabel("Новый пароль").fill(`UI lint platform password ${Date.now()}!`);
    await page.getByRole("button", { name: "Продолжить" }).click();
    await page.getByRole("button", { name: "Показать QR-код" }).click();
    await page.getByLabel("Код из приложения").fill(enrollOtp());
    await page.getByRole("button", { name: "Продолжить" }).click();
    await page.getByRole("button", { name: "Коды сохранены — открыть кабинет" }).click();
    await expect(page).toHaveURL(/\/platform-admin\/$/);
    await ctx.storageState({ path: STATE });
    await ctx.close();
  });

  test("every screen at every width and theme", async ({ browser }, testInfo) => {
    test.setTimeout(60 * 60 * 1000);
    const only = process.env.UI_LINT_ONLY ? new RegExp(process.env.UI_LINT_ONLY) : null;
    const problems: string[] = [];
    for (const theme of THEMES) {
      for (const width of WIDTHS) {
        const plain = await context(browser, width, theme, false);
        const signed = await context(browser, width, theme, true);
        try {
          for (const scene of scenes()) {
            if (only && !only.test(scene.name)) continue;
            const label = `${scene.name} ${width} ${theme}`;
            const page = await (scene.platform ? signed : plain).newPage();
            try {
              await scene.open(page);
              await settled(page);
              const found = [...await lint(page, width <= 430), ...await axe(page)];
              if (found.length) {
                problems.push(...found.map((p) => `${label}: ${p}`));
                await page.screenshot({ path: testInfo.outputPath(`${scene.name}-${width}-${theme}.png`), fullPage: true });
              }
            } catch (error) {
              problems.push(`${label}: экран не открылся — ${String(error).split("\n")[0]}`);
            } finally {
              await page.close();
            }
          }
        } finally {
          await plain.close();
          await signed.close();
        }
      }
    }
    await testInfo.attach("ui-lint.txt", { body: problems.join("\n") || "ok", contentType: "text/plain" });
    expect(problems).toEqual([]);
  });
});
