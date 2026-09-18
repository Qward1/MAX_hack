import { warnUnknown } from "../incidents/presentation";

const employeeStatuses: Record<string, string> = {
  new: "Новая",
  accepted: "Принята исполнителем",
  in_progress: "В работе",
  verification_pending: "На проверке жителей",
  closed: "Результат подтверждён жителем",
  needs_clarification: "Нужно уточнение",
  waiting_external: "Ожидаются сведения внешней стороны",
  cancelled: "Отменена с причиной",
};
const residentStatuses: Record<string, string> = {
  ...employeeStatuses,
  new: "Передано в обработку",
  accepted: "Принято",
  verification_pending: "Проверьте результат",
  closed: "Завершено",
  cancelled: "Работа по заявке отменена",
};
export function ticketStatus(status: string | null, resident = false) {
  const labels = resident ? residentStatuses : employeeStatuses;
  if (status && Object.hasOwn(labels, status)) return labels[status];
  if (status) warnUnknown("ticket status");
  return "Состояние обновилось";
}
export const actionLabels: Record<string, string> = {
  accept: "Принять заявку",
  start: "Начать работу",
  assign: "Назначить",
  "work-attempts": "Сообщить о выполнении",
  clarify: "Запросить уточнение",
  "wait-external": "Ожидать другую службу",
  resume: "Возобновить работу",
  cancel: "Отменить заявку",
  deadlines: "Указать срок",
  observe_result: "Проверить результат",
};
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
