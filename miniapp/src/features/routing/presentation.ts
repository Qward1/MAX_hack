import type { ActionCard, ActionCardAction } from "../../shared/api/client";
import { formatDay } from "../../shared/ui/format";
import { warnUnknown } from "../incidents/presentation";

// Одна дисциплина на все списки действий: интерфейс рисует только тот тип,
// который знает, и ни одного, которого сервер не прислал.
export const cardActionLabels = {
  create_ticket: "Сообщить в управляющую компанию",
  join_existing: "Присоединиться к уже открытой проблеме",
  open_official_channel: "Открыть официальный сервис",
  call_phone: "Позвонить",
  prepare_appeal: "Подготовить текст обращения",
  mark_filed_self_reported: "Я отправил(а) обращение",
  report_to_uk_anyway: "Всё равно сообщить в УК",
};
export type CardActionType = keyof typeof cardActionLabels;

// Аудитория оператора. У жителя эти шаги не появляются ни при каком маршруте.
export const operatorActions = ["operator_review", "route_external", "not_a_problem"];

// Эти действия ведут наружу сами и не требуют обработчика экрана.
export const linkActions: CardActionType[] = ["open_official_channel", "call_phone"];

export const locationScopeLabels: Record<string, string> = {
  apartment: "В квартире",
  house_common: "Общее имущество дома",
  house_territory: "Придомовая территория",
  municipal_territory: "Муниципальная территория",
  external_network: "Внешние сети",
  other_building: "Другое здание",
  unknown: "Не определено",
};
export const dangerLabels: Record<string, string> = {
  gas: "Запах газа",
  smoke_fire: "Дым или огонь",
  electric: "Электричество",
  person_trapped: "Человек не может выйти",
  flooding: "Затопление",
  structural: "Состояние конструкций",
  other_hazard: "Другой признак опасности",
};

export function locationScopeLabel(value: string): string {
  if (Object.hasOwn(locationScopeLabels, value)) return locationScopeLabels[value];
  warnUnknown("location_scope");
  return locationScopeLabels.unknown;
}
export function dangerLabel(value: string): string | null {
  if (Object.hasOwn(dangerLabels, value)) return dangerLabels[value];
  warnUnknown("danger_kind");
  return null;
}

/** Действия карточки, которые житель может увидеть, в порядке backend. */
export function knownCardActions(raw: unknown): ActionCardAction[] {
  if (!Array.isArray(raw)) return [];
  const result: ActionCardAction[] = [];
  for (const action of raw) {
    if (!action || typeof action !== "object" || typeof action.type !== "string") {
      warnUnknown("card_action");
      continue;
    }
    // Шаг оператора молча пропускается: это не «неизвестное» значение.
    if (operatorActions.includes(action.type)) continue;
    if (!Object.hasOwn(cardActionLabels, action.type)) {
      warnUnknown("card_action");
      continue;
    }
    if (typeof action.enabled !== "boolean") continue;
    const url = typeof action.url === "string" ? action.url : null;
    const phone = typeof action.phone === "string" ? action.phone : null;
    if (
      result.some(
        (item) => item.type === action.type && item.url === url && item.phone === phone,
      )
    )
      continue;
    result.push({
      type: action.type as CardActionType,
      label: typeof action.label === "string" && action.label ? action.label : "",
      enabled: action.enabled,
      reason: typeof action.reason === "string" ? action.reason : null,
      url,
      phone,
    });
  }
  return result;
}

/** Подпись действия: сервер даёт свою, шаблон продукта — запасную. */
export function cardActionLabel(action: ActionCardAction): string {
  return action.label || cardActionLabels[action.type as CardActionType];
}

export const UNVERIFIED_NOTE = "Сведения требуют сверки.";

type RouteChecks = Pick<ActionCard["route"], "stale" | "basis" | "channels">;

/**
 * Что именно в маршруте требует сверки — по полям API, без своих порогов:
 * основание (`basis.verification_status`), его давность (`route.stale` без
 * устаревших каналов) и официальные сервисы (`channels[].stale`,
 * `verification_status`). Пустой список — всё проверено. Ничего не
 * объявляет проверенным и не толкует юридически.
 */
export function verificationNotes(route: RouteChecks): string[] {
  const notes: string[] = [];
  const basis = route.basis;
  const channels = route.channels ?? [];
  if (basis && basis.verification_status !== "verified")
    notes.push("Кто отвечает — указано предварительно: основание в справочнике ДомСигнала ещё не сверено.");
  else if (basis && route.stale && !channels.some((channel) => channel.stale))
    notes.push(
      basis.verified_at
        ? `Основание, кто отвечает, сверяли ${formatDay(basis.verified_at)} — нужна повторная сверка.`
        : "Основание, кто отвечает, нужно сверить заново.",
    );
  for (const channel of channels) {
    if (channel.verification_status !== "verified")
      notes.push(`Сведения о сервисе «${channel.label}» ещё не сверены.`);
    else if (channel.stale)
      notes.push(
        channel.verified_at
          ? `Сведения о сервисе «${channel.label}» сверяли ${formatDay(channel.verified_at)} — нужна повторная сверка.`
          : `Сведения о сервисе «${channel.label}» нужно сверить заново.`,
      );
  }
  if (!notes.length && route.stale) notes.push(UNVERIFIED_NOTE);
  return notes;
}
