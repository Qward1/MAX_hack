import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

// UX-1: снимки «до» и «после» одного набора экранов. Долгий прогон, поэтому
// отдельно от обычного: UX_SNAPSHOTS=1 и изолированный стенд с фикстурами
// B14/D2/D3 (см. miniapp/README.md). Сценарий ничего не утверждает о виде —
// он снимает экран и записывает метрики (горизонтальная прокрутка, нарушения
// axe, цели касания меньше 24 px) в <каталог>/metrics.json для сравнения.
// Каталог: UX_SHOTS (по умолчанию test-results/ux/after).
const require = createRequire(import.meta.url);
const SHOTS = process.env.UX_SHOTS ?? "test-results/ux/after";
const THEMES = ["light", "dark"] as const;
const PHONE = [
  { width: 390, height: 844 },
  { width: 320, height: 640 },
];
const WEB = [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];

type Metric = { screen: string; width: number; theme: string; overflow: boolean; axe: string[]; smallTargets: number };
const metrics: Metric[] = [];

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
const key = () => `ux-1-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function context(browser: Browser, size: { width: number; height: number }, theme: string) {
  const ctx = await browser.newContext({
    viewport: size, colorScheme: theme as "light" | "dark", reducedMotion: "reduce", bypassCSP: true,
  });
  ctx.setDefaultTimeout(15000);
  await ctx.route("https://st.max.ru/**", (route) => route.abort());
  return ctx;
}

async function capture(page: Page, name: string, width: number, theme: string) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(150);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") }).catch(() => undefined);
  const axe: string[] = await page
    .evaluate(async () => {
      const w = window as unknown as { axe?: { run: (...a: unknown[]) => Promise<{ violations: { id: string; nodes: unknown[] }[] }> } };
      if (!w.axe) return ["axe-not-loaded"];
      const result = await w.axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"] },
      });
      return result.violations.map((v) => `${v.id}×${v.nodes.length}`);
    })
    .catch(() => ["axe-failed"]);
  const smallTargets = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, summary, [role=button]")]
      .filter((node) => {
        const box = node.getBoundingClientRect();
        if (!box.width || !box.height) return false;
        // Ссылка внутри строки текста — исключение 2.5.8 (inline).
        if (node.tagName === "A" && getComputedStyle(node).display === "inline") return false;
        return box.width < 24 || box.height < 24;
      }).length,
  );
  metrics.push({ screen: name, width, theme, overflow, axe, smallTargets });
  await page.screenshot({ path: `${SHOTS}/${name}-${width}-${theme}.png`, fullPage: true });
}

/** Нажать первую найденную кнопку из списка подписей (подписи «до» и «после» разные). */
async function press(page: Page, names: (string | RegExp)[]) {
  for (const name of names) {
    const button = page.getByRole("button", { name, exact: typeof name === "string" });
    if (await button.count()) {
      await button.first().click();
      return;
    }
  }
  throw new Error(`Нет кнопки: ${names.join(" / ")}`);
}

let ids: { company: string; house: string; other_house: string };
let refs: { incident: string; card: string; draft: string; poll: string | null; ticket: string | null; signal: string | null };

test.describe.serial("UX-1 snapshots", () => {
  test.skip(process.env.UX_SNAPSHOTS !== "1", "Долгий прогон снимков: UX_SNAPSHOTS=1 и стенд с фикстурами");

  test.beforeAll(async ({ request }) => {
    test.setTimeout(180000);
    mkdirSync(SHOTS, { recursive: true });
    ids = run("tests/browser/d3_fixture.py", ["ids"]);
    run("tests/browser/d3_fixture.py", ["binding"]);
    run("tests/browser/d1_fixture.py", ["guest"]);
    const resident = await auth(request, "a16-resident");
    const created = await request.post("/api/v1/reports", {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { house_id: ids.house, category: "elevator", description: "Лифт во втором подъезде стоит с утра, кнопка вызова не горит" },
    });
    expect(created.status()).toBe(201);
    const submitted = await request.post(`/api/v1/houses/${ids.house}/reports/submit`, {
      headers: { ...resident, "Idempotency-Key": key() },
      data: { description: "На улице у остановки не горят фонари, темно" },
    });
    expect(submitted.status()).toBe(201);
    const card = (await submitted.json()).route_outcome_id;
    const draft = await request.post("/api/v1/appeal-drafts", {
      headers: resident, data: { house_id: ids.house, route_outcome_id: card },
    });
    const feed = await (await request.get(`/api/v1/houses/${ids.house}/announcements`, { headers: resident })).json();
    const poll = feed.items.find((item: { poll?: { poll_id: string } }) => item.poll)?.poll?.poll_id ?? null;
    const admin = await auth(request, "a16-admin");
    const tickets = await (await request.get(`/api/v1/tickets?house_id=${ids.house}&limit=5`, { headers: admin })).json();
    let signal: string | null = null;
    try {
      run("tests/browser/signal_fixture.py", ["prepare"]);
      signal = run("tests/browser/signal_fixture.py", ["gas"]).signal_id;
    } catch {
      signal = null;
    }
    refs = {
      incident: (await created.json()).incident.id, card, draft: (await draft.json()).id, poll,
      ticket: tickets.items?.[0]?.id ?? null, signal,
    };
  });

  test.afterAll(() => {
    writeFileSync(`${SHOTS}/metrics.json`, JSON.stringify(metrics, null, 2));
  });

  for (const theme of THEMES)
    for (const size of PHONE)
      test(`mini app ${size.width} ${theme}`, async ({ browser }) => {
        test.setTimeout(300000);
        const ctx: BrowserContext = await context(browser, size, theme);
        const page = await ctx.newPage();
        const base = `/?test_actor=a16-resident&house=${ids.house}`;
        try {
          const screens: [string, string][] = [
            ["r-board", base],
            ["r-board-demo", "/?test_actor=demo"],
            ["r-report-form", `${base}&report=1`],
            ["r-incident", `${base}&incident=${refs.incident}`],
            ["r-card", `${base}&card=${refs.card}`],
            ["r-draft", `${base}&draft=${refs.draft}`],
            ["r-home", `${base}&view=home`],
            ["r-news", `${base}&view=news`],
            ["r-works", `${base}&view=works`],
            ["r-mine", `${base}&view=mine`],
            ["r-reception", `${base}&view=reception`],
            ["r-chooser", "/?test_actor=a16-admin"],
            ["r-nohouse", "/?test_actor=d1-guest"],
          ];
          if (refs.poll) screens.push(["r-poll", `${base}&view=poll&poll=${refs.poll}`]);
          for (const [name, url] of screens) {
            await page.goto(url);
            await expect(page.locator("h1").first()).toBeVisible();
            await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
            await capture(page, name, size.width, theme);
          }
          // Шаг «Проверьте, что мы поняли».
          await page.goto(`${base}&report=1`);
          await page.getByRole("textbox").first().fill("опять лифт во втором подъезде стоит");
          await press(page, ["Дальше", "Проверить описание", /^Проверить/]);
          await expect(page.getByRole("heading", { name: "Проверьте, что мы поняли" })).toBeVisible();
          await capture(page, "r-review", size.width, theme);
          // Ошибка загрузки доски.
          await page.route("**/api/v1/houses/*/incidents*", (route) =>
            route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({
              type: "about:blank", title: "", status: 503, detail: "", code: "unavailable", trace_id: "ux-1", retryable: true }) }));
          await page.goto(base);
          await expect(page.locator("h1").first()).toBeVisible();
          await page.waitForTimeout(300);
          await capture(page, "r-error", size.width, theme);
          await page.unroute("**/api/v1/houses/*/incidents*");
        } finally {
          await ctx.close();
        }
      });

  for (const theme of THEMES)
    for (const size of WEB)
      test(`web ${size.width} ${theme}`, async ({ browser }) => {
        test.setTimeout(300000);
        const ctx = await context(browser, size, theme);
        const page = await ctx.newPage();
        const q = `company=${ids.company}&test_actor=a16-admin`;
        try {
          const screens: [string, string][] = [
            ["w-site", "/site"],
            ["w-login", "/login"],
            ["w-apply", "/company/apply"],
            ["w-overview", `/admin/?${q}`],
            ["w-tickets", `/admin/tickets?${q}`],
            ["w-houses", `/admin/houses?${q}`],
            ["w-staff", `/admin/staff?${q}`],
            ["w-chats", `/admin/max?${q}`],
            ["w-org", `/admin/organization?${q}`],
            ["w-mailings", `/admin/mailings?${q}`],
            ["w-operator", `/admin/?company=${ids.company}&test_actor=a16-operator`],
          ];
          if (refs.ticket) screens.push(["w-ticket", `/admin/?${q}&ticket=${refs.ticket}`]);
          screens.push(["w-signals", `/admin/?test_actor=p5-operator&section=signals`]);
          if (refs.signal) screens.push(["w-signal", `/admin/?test_actor=p5-operator&section=signals&signal=${refs.signal}`]);
          for (const [name, url] of screens) {
            await page.goto(url);
            await expect(page.locator("h1").first()).toBeVisible();
            await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
            await page.waitForTimeout(400);
            await capture(page, name, size.width, theme);
          }
        } finally {
          await ctx.close();
        }
      });
});
