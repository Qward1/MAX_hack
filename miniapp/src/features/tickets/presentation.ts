import { warnUnknown } from "../incidents/presentation";
import { residentTicketStatus, staffTicketStatus, statusOf } from "../../shared/ui/status";

/** Подпись статуса заявки — из общего словаря (shared/ui/status.ts). */
export function ticketStatus(status: string | null, resident = false) {
  return statusOf(resident ? residentTicketStatus : staffTicketStatus, status).label;
}
export const actionLabels: Record<string, string> = {
  accept: "Принять заявку",
  start: "Начать работу",
  assign: "Назначить исполнителя",
  "work-attempts": "Сообщить о выполнении",
  clarify: "Запросить уточнение",
  "wait-external": "Ожидать другую службу",
  resume: "Возобновить работу",
  cancel: "Отменить заявку",
  deadlines: "Указать срок",
  observe_result: "Проверить результат",
};
/**
 * Подпись действия с учётом заявки: при указанном исполнителе назначение —
 * это замена, а принятие без исполнителя — «взять в работу» себе.
 */
export function actionLabel(code: string, ticket: { assignee_id?: string | null }): string {
  if (code === "accept" && !ticket.assignee_id) return "Взять в работу";
  if (code === "assign" && ticket.assignee_id) return "Изменить исполнителя";
  return actionLabels[code] ?? code;
}
export type PresentedAction = {
  code: string;
  enabled: boolean;
  reason?: string;
};
export function ticketActions(value: unknown): PresentedAction[] {
  if (!Array.isArray(value)) return [];
  const result = new Map<string, PresentedAction>();
  for (const entry of value) {
    // A-16 publishes strings. Tolerate a future disabled descriptor, fail closed otherwise.
    const code = typeof entry === "string" ? entry : entry?.code;
    if (typeof code !== "string" || !Object.hasOwn(actionLabels, code)) {
      warnUnknown("ticket action");
      continue;
    }
    result.set(code, {
      code,
      enabled: typeof entry === "string" || entry.enabled === true,
      reason: typeof entry?.reason === "string" ? entry.reason : undefined,
    });
  }
  return [...result.values()];
}
export const eventLabels: Record<string, string> = {
  created: "Заявка создана",
  assigned: "Исполнитель назначен",
  accepted: "Заявка принята",
  started: "Работа начата",
  clarification_requested: "Запрошено уточнение",
  external_wait_recorded: "Ожидание внешней стороны",
  resumed: "Работа возобновлена",
  work_reported: "Исполнитель сообщил о выполнении",
  result_confirmed: "Житель подтвердил результат",
  result_objected: "Житель сообщил, что проблема осталась",
  observation_recorded: "Наблюдение сохранено",
  cancelled: "Заявка отменена",
  deadline_recorded: "Срок обновлён",
};
