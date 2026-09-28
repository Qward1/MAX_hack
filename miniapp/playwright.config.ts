import { defineConfig } from "@playwright/test";
export default defineConfig({
  // Браузерные сценарии, проверка вёрстки F1 (§2.5) и приёмочные кейсы (§3).
  testDir: "./tests",
  testMatch: ["browser/**/*.spec.ts", "ui-lint.spec.ts", "acceptance/**/*.spec.ts"],
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  reporter: "list",
  outputDir: "test-results",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8017",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
