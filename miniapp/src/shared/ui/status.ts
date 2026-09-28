/**
 * Словарь статусов: одно место на жителя и одно на сотрудника.
 *
 * Смысл статусов задаёт backend — здесь только подпись (состояние, а не
 * действие), тон, знак и одна фраза «что дальше». Фраза описывает порядок
 * работы продукта и ничего не обещает сверх него. Неизвестное значение —
 * нейтральное «Состояние обновилось», а не выдуманный статус.
 */
export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export type StatusEntry = {
  label: string;
  tone: Tone;
  /** Что будет дальше — одна фраза; пусто, если системе это неизвестно. */
  next?: string;
};

export const TONE_MARK: Record<Tone, string> = {
  neutral: "○",
  info: "●",
  success: "✓",
  warning: "!",
  danger: "!",
};

export const UNKNOWN_STATUS: StatusEntry = {
  label: "Состояние обновилось",
  tone: "neutral",
  next: "Подробности появятся после обновления данных.",
};

/** Проблема дома (Incident) — для жителя. */
export const residentIncidentStatus: Record<string, StatusEntry> = {
  detected: { label: "Замечена", tone: "info", next: "Соседи видят её на доске дома." },
  open: { label: "Открыта", tone: "info", next: "Соседи видят её на доске дома." },
  reported: {
    label: "Житель отметил отправку",
    tone: "info",
    next: "Регистрацию во внешней системе ДомСигнал не подтверждает.",
  },
  overdue: { label: "Срок истёк", tone: "warning" },
  escalated: { label: "На следующем уровне", tone: "info" },
  resolved: { label: "Решена", tone: "success", next: "Жители подтвердили, что исправлено." },
  // F1: проблема закрыта отменой её заявки управляющей компанией.
  dismissed: { label: "Закрыта", tone: "neutral", next: "Управляющая компания отменила заявку." },
};

/** Заявка в управляющую компанию (Ticket) — как её видит житель. */
export const residentTicketStatus: Record<string, StatusEntry> = {
  new: { label: "Ждёт исполнителя", tone: "info", next: "Сотрудник управляющей компании возьмёт заявку в работу." },
  accepted: { label: "Принята", tone: "info", next: "Исполнитель назначен, работа ещё не начата." },
  in_progress: {
    label: "В работе",
    tone: "info",
    next: "Когда исполнитель сообщит о выполнении, вы сможете проверить результат.",
  },
  verification_pending: {
    label: "Ждёт проверки жителями",
    tone: "warning",
    next: "Исполнитель сообщил о выполнении. Проверьте, исправлено ли.",
  },
  closed: { label: "Завершена", tone: "success", next: "Жители подтвердили результат." },
  needs_clarification: {
    label: "Нужно уточнение",
    tone: "warning",
    next: "Управляющая компания уточняет подробности.",
  },
  waiting_external: {
    label: "Ждёт другую организацию",
    tone: "neutral",
    next: "Работа зависит от другой организации.",
  },
  cancelled: { label: "Отменена", tone: "neutral", next: "Работа по заявке отменена." },
};

/** Заявка — для сотрудника. */
export const staffTicketStatus: Record<string, StatusEntry> = {
  new: { label: "Новая", tone: "info", next: "Назначьте исполнителя или возьмите в работу." },
  accepted: { label: "Принята", tone: "info", next: "Исполнитель начинает работу." },
  in_progress: { label: "В работе", tone: "info", next: "Когда работа выполнена, сообщите о выполнении." },
  verification_pending: {
    label: "Ждёт проверки жителями",
    tone: "warning",
    next: "Жители проверяют результат. Отчёт исполнителя не закрывает заявку.",
  },
  closed: { label: "Закрыта: жители подтвердили", tone: "success" },
  needs_clarification: { label: "Нужно уточнение", tone: "warning" },
  waiting_external: { label: "Ждёт другую организацию", tone: "neutral" },
  cancelled: { label: "Отменена", tone: "neutral" },
};

/**
 * «Что дальше» у новой заявки зависит от исполнителя: пока его нет — назначить
 * или взять себе, после назначения — исполнитель принимает заявку.
 */
export function staffTicketNext(status: string | null | undefined, hasAssignee: boolean): string | undefined {
  if (status === "new" && hasAssignee) return "Исполнитель назначен и должен принять заявку.";
  return undefined;
}

/** Сигнал из домового чата — только для сотрудника. */
export const signalStatus: Record<string, StatusEntry> = {
  new: { label: "Новый", tone: "info", next: "Нужно решение оператора." },
  in_review: { label: "Маршрут выбран", tone: "info", next: "Примите решение по сигналу." },
  converted: { label: "Заявка создана", tone: "success" },
  routed_external: { label: "Внешний маршрут", tone: "neutral" },
  dismissed: { label: "Закрыт", tone: "neutral" },
};

/** Сила сигнала: опасное отличается и текстом, и тоном. */
export const signalStrength: Record<string, StatusEntry> = {
  critical: { label: "Критический", tone: "danger" },
  strong: { label: "Сильный", tone: "warning" },
  medium: { label: "Средний", tone: "info" },
  weak: { label: "Возможный", tone: "neutral" },
};

export function statusOf(dictionary: Record<string, StatusEntry>, value: string | null | undefined): StatusEntry {
  if (value && Object.hasOwn(dictionary, value)) return dictionary[value];
  if (value && import.meta.env.DEV) console.warn("[ДомСигнал] Неизвестное значение: status");
  return UNKNOWN_STATUS;
}
