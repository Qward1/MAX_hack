import type { components } from "../../shared/api/schema";
import type { ReportCreate } from "../../shared/api/client";

export const categoryLabels: Record<ReportCreate["category"], string> = {
  elevator: "Лифт",
  water: "Вода",
  lighting: "Освещение",
  waste: "Отходы",
  other: "Другое",
};
export const statusLabels: Record<string, string> = {
  detected: "Обнаружена проблема",
  open: "Открыта",
  reported: "Житель отметил отправку",
  overdue: "Срок истёк",
  escalated: "Передано на следующий уровень",
  resolved: "Решена",
  dismissed: "Не подтверждена",
};
export const actionLabels = {
  prepare_appeal: "Подготовить обращение",
  edit_draft: "Редактировать черновик",
  join: "Меня тоже касается",
  copy_draft: "Скопировать текст",
  open_official_channel: "Открыть официальный сервис",
  mark_filed: "Я отправил(а) обращение",
  mark_resolved: "Проблема решена",
  mark_unresolved: "Проблема остаётся",
  escalate: "Следующий уровень обращения",
  report_not_problem: "Сообщить об ошибке",
  retry: "Обновить данные",
};
export type ActionCode = keyof typeof actionLabels;
export type ActionDescriptor = components["schemas"]["ActionDescriptor"];
export type Source = Omit<components["schemas"]["Provenance"], "origin"> & {
  origin: string | null;
};

export function warnUnknown(kind: string) {
  // Never log payloads (including auth data, descriptions or unknown server strings).
  if (import.meta.env.DEV)
    console.warn(`[ДомСигнал] Неизвестное значение: ${kind}`);
}
export function categoryLabel(value: string): string {
  if (Object.hasOwn(categoryLabels, value))
    return categoryLabels[value as keyof typeof categoryLabels];
  warnUnknown("category");
  return "Другая проблема дома";
}

export function knownActions(raw: unknown): ActionDescriptor[] {
  if (!Array.isArray(raw)) return [];
  const result: ActionDescriptor[] = [];
  for (const action of raw) {
    if (
      !action ||
      typeof action !== "object" ||
      !Object.hasOwn(actionLabels, action.code)
    ) {
      warnUnknown("allowed_action");
      continue;
    }
    if (
      typeof action.enabled !== "boolean" ||
      result.some((item) => item.code === action.code)
    )
      continue;
    result.push({
      code: action.code,
      enabled: action.enabled,
      reason: typeof action.reason === "string" ? action.reason : null,
    });
  }
  return result;
}

export function formatDay(value?: string | null): string | null {
  // Дата проверки справочника приходит без времени; выдумывать его не нужно.
  if (!value) return null;
  const date = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat("ru", { dateStyle: "long", timeZone: "UTC" }).format(date);
}

export function formatDate(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat("ru", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
