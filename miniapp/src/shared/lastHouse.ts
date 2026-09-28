/**
 * Последний выбранный житель дом — только удобство этого устройства (D-01).
 *
 * Хранилище браузера в MAX может быть недоступно или пустым: тогда при
 * нескольких домах житель выбирает дом сам, а не попадает на первый по
 * алфавиту. Доступ всё равно проверяет сервер — запись лишь подсказка.
 */
const KEY = "ds:last-house:";

export function rememberHouse(userId: string, houseId: string): void {
  try {
    window.localStorage.setItem(KEY + userId, houseId);
  } catch {
    /* хранилище недоступно — выбор просто не запоминается */
  }
}

export function lastHouse(userId: string): string | null {
  try {
    return window.localStorage.getItem(KEY + userId);
  } catch {
    return null;
  }
}
