// HTML-слайды 1280×720 → PDF. Запуск из miniapp/: node ../docs/presentation/print_pdf.mjs <in.html> <out.pdf>
// Браузер — Chromium Playwright; если он не скачан, установленный Chrome (PLAYWRIGHT_CHANNEL=chrome).
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(path.join(process.cwd(), "package.json"));
const { chromium } = require("playwright");
const [input, output] = process.argv.slice(2);

async function launch() {
  const channel = process.env.PLAYWRIGHT_CHANNEL;
  if (channel) return chromium.launch({ channel });
  try {
    return await chromium.launch();
  } catch {
    return chromium.launch({ channel: "chrome" });
  }
}

const browser = await launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "load" });
  await page.pdf({ path: path.resolve(output), width: "1280px", height: "720px", printBackground: true,
    margin: { top: "0", right: "0", bottom: "0", left: "0" } });
} finally {
  await browser.close();
}
