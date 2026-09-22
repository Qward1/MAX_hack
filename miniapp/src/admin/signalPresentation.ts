import { warnUnknown } from "../features/incidents/presentation";
import type { SignalActionCode } from "../shared/api/signals";

// Подписи очереди сигналов. Смысл и разрешения приходят с сервера; здесь
// только слова для уже известных значений и безопасный запасной вариант.

export const strengthLabels: Record<string, string> = {
  critical: "Критический",
  strong: "Сильный",
  medium: "Средний",
  weak: "Возможный",
};

export const statusLabels: Record<string, string> = {
  new: "Новый",
  in_review: "Маршрут выбран",
  converted: "Заявка создана",
  routed_external: "Внешний маршрут",
  dismissed: "Закрыт",
};

// Значок маршрута в очереди: коротко и без названий организаций.
export const routeBadgeLabels: Record<string, string> = {
  uk_internal: "УК",
  municipality: "Муниципалитет",
  resource_supplier: "Ресурсник",
  emergency_service: "Экстренные службы",
  regional_operator: "Региональный оператор",
  other_authority: "Другой орган",
  unknown: "Не определён",
};

// Полная подпись маршрута для выбора оператором.
export const routeChoiceLabels: Record<string, string> = {
  uk_internal: "Управляющая компания дома",
  municipality: "Муниципалитет",
  resource_supplier: "Ресурсоснабжающая организация",
  emergency_service: "Экстренные службы",
  regional_operator: "Региональный оператор",
  other_authority: "Другой орган власти",
};

export const dismissReasons: [string, string][] = [
  ["not_a_problem", "Не проблема"],
  ["duplicate", "Дубликат"],
  ["resolved", "Уже решено"],
  ["out_of_scope", "Не относится к дому"],
  ["spam", "Спам или флуд"],
];

export const signalActionLabels: Record<SignalActionCode, string> = {
  "create-ticket": "Создать заявку",
  join: "Присоединить к проблеме",
  "route-external": "Отметить внешний маршрут",
  "choose-route": "Выбрать маршрут",
  dismiss: "Закрыть",
};

export const statusFilters: [string, string, string[]][] = [
  ["open", "Новые", ["new", "in_review"]],
  ["converted", "Заявка создана", ["converted"]],
  ["routed_external", "Внешний маршрут", ["routed_external"]],
  ["dismissed", "Закрытые", ["dismissed"]],
  ["all", "Все", []],
];

export const strengthFilters: [string, string][] = [
  ["any", "Любая сила"],
  ["critical", "Критические"],
  ["strong", "Сильные"],
  ["medium", "Средние"],
  ["weak", "Возможные"],
];

export const categoryOptions: [string, string][] = [
  ["elevator", "Лифт"],
  ["water", "Вода"],
  ["lighting", "Освещение"],
  ["waste", "Отходы"],
  ["other", "Другое"],
];

export function label(
  map: Record<string, string>,
  value: string,
  kind: string,
): string {
  if (Object.hasOwn(map, value)) return map[value];
  warnUnknown(kind);
  return "Состояние обновилось";
}

/** Команды оператора, которые экран умеет выполнять, в порядке сервера. */
export function knownSignalActions(
  raw: unknown,
): { code: SignalActionCode; enabled: boolean; reason: string | null }[] {
  if (!Array.isArray(raw)) return [];
  const result: {
    code: SignalActionCode;
    enabled: boolean;
    reason: string | null;
  }[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object" || typeof item.code !== "string")
      continue;
    if (!Object.hasOwn(signalActionLabels, item.code)) {
      warnUnknown("signal_action");
      continue;
    }
    if (typeof item.enabled !== "boolean") continue;
    if (result.some((known) => known.code === item.code)) continue;
    result.push({
      code: item.code as SignalActionCode,
      enabled: item.enabled,
      reason: typeof item.reason === "string" ? item.reason : null,
    });
  }
  return result;
}

/** Дата проверки справочника — только день, без выдуманного времени. */
export function formatDay(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return new Intl.DateTimeFormat("ru", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

/** «14:05», а для не сегодняшнего дня — «21 сент., 14:05». */
export function shortTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const time = new Intl.DateTimeFormat("ru", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return time;
  const day = new Intl.DateTimeFormat("ru", {
    day: "numeric",
    month: "short",
  }).format(date);
  return `${day}, ${time}`;
}

export function plural(
  count: number,
  one: string,
  few: string,
  many: string,
): string {
  const tens = count % 100;
  const units = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (units === 1) return one;
  if (units >= 2 && units <= 4) return few;
  return many;
}

export function countsLine(
  reports: number,
  authors: number,
  last: string,
): string {
  return `${reports} ${plural(reports, "реплика", "реплики", "реплик")} · ${authors} ${plural(
    authors,
    "житель",
    "жителя",
    "жителей",
  )} · последняя в ${shortTime(last)}`;
}
