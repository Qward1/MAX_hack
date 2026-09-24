export type Surface = "miniapp" | "landing";

/**
 * Что открывает корень сайта (SITE-ENTRY-2026-09-26).
 *
 * Подписанные стартовые данные MAX (`initData`) — тот же признак, по которому
 * мини-приложение уже входит; скрипт MAX Bridge подключён синхронно в `<head>`
 * до этого модуля. Без них: на production — лендинг; на локальном и тестовом
 * стенде с тестовым входом — мини-приложение (браузерные проверки и демо).
 * Сбой запроса возможностей — лендинг: жителю вне MAX мини-приложение без
 * входа всё равно недоступно.
 */
export async function chooseSurface(
  initData: () => string,
  request: (input: string, init?: RequestInit) => Promise<Response>,
): Promise<Surface> {
  if (initData()) return "miniapp";
  let testStand = false;
  try {
    const response = await request("/api/v1/capabilities", { cache: "no-store" });
    if (response.ok) {
      const caps = (await response.json()) as { environment?: string; features?: { test_auth?: boolean } };
      testStand = caps.environment !== "production" && caps.features?.test_auth === true;
    }
  } catch {
    testStand = false;
  }
  // Повторная проверка: если мост MAX заполнил данные чуть позже, это всё же MAX.
  return initData() || testStand ? "miniapp" : "landing";
}
