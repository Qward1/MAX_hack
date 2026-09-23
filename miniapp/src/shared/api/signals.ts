import type { components } from "./schema";
import { TicketClient } from "./tickets";

type Schema = components["schemas"];
export type SignalList = Schema["SignalList"];
export type SignalSummary = Schema["SignalSummary"];
export type SignalView = Schema["SignalView"];
export type SignalMutation = Schema["SignalMutation"];
export type SignalActionCode = Schema["SignalActionDescriptor"]["code"];
export type SignalQuote = Schema["SignalQuoteView"];
export type SignalCommand =
  | Schema["SignalCreateTicket"]
  | Schema["SignalJoin"]
  | Schema["SignalRouteExternal"]
  | Schema["SignalChooseRoute"]
  | Schema["SignalDismiss"];

export type SignalQuery = {
  house?: string;
  statuses: string[];
  strengths: string[];
  limit: number;
  offset: number;
};

// Та же сессия сотрудника и тот же клиент, что у очереди заявок: CSRF, куки,
// Problem Details и таймаут общие. Доступ проверяет только сервер.
export class SignalClient extends TicketClient {
  signals(query: SignalQuery, signal?: AbortSignal) {
    const params = new URLSearchParams({
      limit: String(query.limit),
      offset: String(query.offset),
    });
    if (query.house) params.set("house_id", query.house);
    for (const status of query.statuses) params.append("status", status);
    for (const strength of query.strengths) params.append("strength", strength);
    return this.request<SignalList>(`/api/v1/signals?${params}`, { signal });
  }
  signalDetail(id: string, signal?: AbortSignal) {
    return this.request<SignalView>(
      `/api/v1/signals/${encodeURIComponent(id)}`,
      {
        signal,
      },
    );
  }
  decide(
    id: string,
    action: SignalActionCode,
    payload: SignalCommand,
    key: string,
  ) {
    return this.request<SignalMutation>(
      `/api/v1/signals/${encodeURIComponent(id)}/${action}`,
      {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Idempotency-Key": key },
      },
    );
  }
}
export const signalClient = new SignalClient();
