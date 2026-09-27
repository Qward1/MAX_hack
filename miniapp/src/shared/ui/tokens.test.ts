import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Контраст пар токенов в обеих темах (WCAG 2.2 AA): текст ≥ 4.5:1,
 * границы полей и индикатор фокуса ≥ 3:1. Значения читаются из tokens.css —
 * второго источника правды нет.
 */

// Тесты запускаются из каталога miniapp (npm run test, check.py --scope frontend).
const css = readFileSync("src/shared/styles/tokens.css", "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--ds-([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2].toLowerCase()]));
}
const light = block(":root {");
const dark = { ...light, ...block(':root[data-theme="dark"] {') };

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratio(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

// [текст или элемент, фон, минимум]
const PAIRS: [string, string, number][] = [
  ["ink", "bg", 4.5],
  ["ink", "surface", 4.5],
  ["ink", "surface-2", 4.5],
  ["ink-2", "bg", 4.5],
  ["ink-2", "surface", 4.5],
  ["ink-2", "surface-2", 4.5],
  ["accent", "bg", 4.5],
  ["accent", "surface", 4.5],
  ["accent", "accent-soft", 4.5],
  ["on-action", "action", 4.5],
  ["on-action", "action-hover", 4.5],
  ["secondary-ink", "secondary", 4.5],
  ["disabled-ink", "disabled", 4.5],
  ["danger", "surface", 4.5],
  ["danger", "danger-soft", 4.5],
  ["warning", "warning-soft", 4.5],
  ["success", "success-soft", 4.5],
  ["info", "info-soft", 4.5],
  ["ink", "danger-soft", 4.5],
  ["ink", "warning-soft", 4.5],
  ["ink", "success-soft", 4.5],
  ["ink", "info-soft", 4.5],
  ["ink-2", "info-soft", 4.5],
  // Кнопка «Позвонить 112»: текст цвета поверхности на красном.
  ["surface", "danger", 4.5],
  // Подтверждение необратимого действия: сплошная красная кнопка.
  ["on-danger", "danger-action", 4.5],
  // Не текст: граница поля, фокус, рамка блока безопасности.
  ["field", "surface", 3],
  ["field", "bg", 3],
  ["focus", "bg", 3],
  ["focus", "surface", 3],
  ["danger", "bg", 3],
];

describe.each([
  ["светлая", light],
  ["тёмная", dark],
])("контраст токенов: %s тема", (_name, theme) => {
  it.each(PAIRS)("%s на %s ≥ %d:1", (fore, back, minimum) => {
    expect(theme[fore], fore).toBeTruthy();
    expect(theme[back], back).toBeTruthy();
    expect(ratio(theme[fore], theme[back])).toBeGreaterThanOrEqual(minimum);
  });
});

describe("тёмная тема — полноценная, а не инверсия", () => {
  it("совпадает в обоих способах включения", () => {
    const media = css.slice(css.indexOf("@media (prefers-color-scheme: dark)"));
    const inner = media.slice(media.indexOf("{", media.indexOf(":root:not")) + 1, media.indexOf("}", media.indexOf(":root:not")));
    const fromMedia = Object.fromEntries([...inner.matchAll(/--ds-([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2].toLowerCase()]));
    expect(fromMedia).toEqual(block(':root[data-theme="dark"] {'));
  });
  it("задаёт каждый цвет светлой темы", () => {
    for (const name of Object.keys(light)) expect(Object.hasOwn(block(':root[data-theme="dark"] {'), name), name).toBe(true);
  });
});
