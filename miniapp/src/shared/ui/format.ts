/**
 * Одно место форматирования дат и числительных на всё приложение.
 *
 * Житель видит относительные даты по своим часам: «сегодня, 14:05»,
 * «вчера, 09:30», дальше — «12 сентября». Сотрудник видит точное время по
 * Москве с пометкой «МСК»: так в проекте считаются тихие часы и сводка.
 */
const LOCALE = "ru";
export const STAFF_TIME_ZONE = "Europe/Moscow";

const plurals = new Intl.PluralRules(LOCALE);

/** Форма слова для числа: `["сосед", "соседа", "соседей"]`. */
export function pluralize(count: number, forms: readonly [string, string, string]): string {
  const rule = plurals.select(count);
  return rule === "one" ? forms[0] : rule === "few" ? forms[1] : forms[2];
}

/** «1 сосед», «3 соседа», «5 соседей». */
export function countLabel(count: number, forms: readonly [string, string, string]): string {
  return `${count} ${pluralize(count, forms)}`;
}

function parse(value?: string | null): Date | null {
  if (!value) return null;
  // Дата без времени («2026-09-20») — это день, а не полночь по UTC.
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00` : value);
  return Number.isFinite(date.getTime()) ? date : null;
}

function dayKey(date: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function relative(date: Date, now: Date, timeZone?: string): string {
  const time = new Intl.DateTimeFormat(LOCALE, { timeZone, hour: "2-digit", minute: "2-digit" }).format(date);
  const today = dayKey(now, timeZone);
  const yesterday = dayKey(new Date(now.getTime() - 86_400_000), timeZone);
  const key = dayKey(date, timeZone);
  if (key === today) return `сегодня, ${time}`;
  if (key === yesterday) return `вчера, ${time}`;
  const sameYear = key.slice(0, 4) === today.slice(0, 4);
  const day = new Intl.DateTimeFormat(LOCALE, {
    timeZone, day: "numeric", month: "long", ...(sameYear ? {} : { year: "numeric" }),
  }).format(date);
  return sameYear ? `${day}, ${time}` : day;
}

/** Для жителя: «сегодня, 14:05», «вчера, 09:30», «12 сентября, 10:15», «3 марта 2025 г.». */
export function formatWhen(value?: string | null, now: Date = new Date()): string | null {
  const date = parse(value);
  return date ? relative(date, now) : null;
}

/** Для сотрудника в списках: то же, но по Москве и с «МСК». */
export function formatStaffWhen(value?: string | null, now: Date = new Date()): string | null {
  const date = parse(value);
  return date ? `${relative(date, now, STAFF_TIME_ZONE)} МСК` : null;
}

/** Для сотрудника точно: «26.09.2026, 14:05 МСК». */
export function formatStaffTime(value?: string | null): string | null {
  const date = parse(value);
  if (!date) return null;
  return `${new Intl.DateTimeFormat(LOCALE, {
    timeZone: STAFF_TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(date)} МСК`;
}

/** Только день — для даты проверки справочника: «20 сентября 2026 г.». Время не выдумываем. */
export function formatDay(value?: string | null): string | null {
  if (!value) return null;
  const day = /^\d{4}-\d{2}-\d{2}/.exec(value)?.[0];
  const date = day ? new Date(`${day}T12:00:00Z`) : parse(value);
  if (!date || !Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: "long", timeZone: "UTC" }).format(date);
}
