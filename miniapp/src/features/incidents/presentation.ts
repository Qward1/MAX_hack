import type {
  IncidentDetail,
  IncidentSummary,
  ReportCreate,
} from "../../shared/api/client";

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
  escalated: "Передано выше",
  resolved: "Решена",
  dismissed: "Не подтверждена",
};
export const actionLabels = {
  view: "Открыть",
  prepare_appeal: "Подготовить обращение",
  edit_draft: "Редактировать черновик",
  join: "Меня тоже касается",
  copy_draft: "Скопировать текст",
  open_official_channel: "Открыть официальный канал",
  mark_filed: "Я отправил(а) обращение",
  mark_resolved: "Проблема решена",
  mark_unresolved: "Проблема остаётся",
  escalate: "Следующий уровень обращения",
  report_not_problem: "Сообщить об ошибке",
  retry: "Обновить данные",
};
export type ActionCode = keyof typeof actionLabels;
export type ActionDescriptor = {
  code: ActionCode;
  enabled: boolean;
  reason: string | null;
};
export type Source = {
  type: string;
  source_title?: string | null;
  source_url?: string | null;
  verified_at?: string | null;
  recorded_at?: string | null;
  note?: string | null;
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

// C0's only legacy string action is a read action. Never convert an arbitrary string into permission.
// Object descriptors are accepted defensively for forward compatibility, not fabricated from status.
export function knownActions(raw: unknown): ActionDescriptor[] {
  if (!Array.isArray(raw)) return [];
  const result: ActionDescriptor[] = [];
  for (const entry of raw) {
    const action =
      entry === "view" ? { code: "view", enabled: true, reason: null } : entry;
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

export function formatDate(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat("ru", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

// C0 verification_status does NOT establish provenance.type=official/user_reported.
// Only its explicit demo marker has equivalent meaning. No invented source on the board.
export function ruleSource(
  rule: IncidentDetail["rule"] | null | undefined,
): Source | null {
  if (!rule) return null;
  return {
    type: rule.verification_status === "demo" ? "demo" : "unknown",
    source_title: rule.source_title,
    source_url: rule.source_url,
    note: rule.note,
  };
}
export function canView(incident: IncidentSummary): boolean {
  return knownActions(incident.allowed_actions).some(
    (action) => action.code === "view" && action.enabled,
  );
}
