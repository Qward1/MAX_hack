import { warnUnknown } from "../features/incidents/presentation";
import type { SignalActionCode } from "../shared/api/signals";
import { countLabel, formatDay as formatDayOnly, formatStaffWhen, pluralize } from "../shared/ui/format";

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
  return formatDayOnly(value) ?? "";
}

/** «сегодня, 14:05 МСК», «вчера, 09:30 МСК», «21 сентября, 14:05 МСК». */
export function shortTime(value?: string | null): string {
  return formatStaffWhen(value) ?? "";
}

export function plural(count: number, one: string, few: string, many: string): string {
  return pluralize(count, [one, few, many]);
}

export function countsLine(reports: number, authors: number, last: string): string {
  return `${countLabel(reports, ["реплика", "реплики", "реплик"])} · ${countLabel(authors, [
    "житель",
    "жителя",
    "жителей",
  ])} · последняя ${shortTime(last)}`;
}
