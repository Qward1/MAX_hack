import type { components } from "../../shared/api/schema";
import type { ReportCreate } from "../../shared/api/client";
import { formatDay as formatDayOnly, formatWhen } from "../../shared/ui/format";
import { residentIncidentStatus } from "../../shared/ui/status";

export const categoryLabels: Record<ReportCreate["category"], string> = {
  elevator: "Лифт",
  water: "Вода",
  lighting: "Освещение",
  waste: "Отходы",
  other: "Другое",
};
/** Подписи статусов проблемы — из общего словаря (shared/ui/status.ts). */
export const statusLabels: Record<string, string> = Object.fromEntries(
  Object.entries(residentIncidentStatus).map(([code, entry]) => [code, entry.label]),
);
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

/** День проверки справочника — без выдуманного времени (shared/ui/format.ts). */
export const formatDay = formatDayOnly;

/** Дата для жителя: «сегодня, 14:05» (shared/ui/format.ts). */
export const formatDate = formatWhen;
